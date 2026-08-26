"""Explicit gpt-auto turn workflow and no-double-submit boundary."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.agent_session import (
    CorrelationQuality,
    ObservationSink,
    SessionPrompt,
    SessionTurnResult,
    TransportObservation,
    TransportObservationKind,
)
from audiagentic.foundation.transports.session_binding import (
    ProviderSessionBindingUpdate,
    ProviderSessionRef,
)
from audiagentic.foundation.workflow import TransitionConfig, TransitionEngine

from .chat import ChatState, PersistentChat
from .observation_engine import (
    EvidenceCapability,
    Observation,
    ObservationOutcome,
    ObservationTracker,
)
from .prompt_fingerprint import PromptFingerprint, match_prompt
from .snapshot import ChatMessageRef, ChatSnapshot
from .urls import parse_provider_session_id

logger = logging.getLogger(__name__)


def _text_digest(text: str | None) -> str | None:
    """Return a bounded diagnostic fingerprint without logging response text."""
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _advance_with_trace(
    tracker: ObservationTracker,
    observation: Observation,
    now: float,
    *,
    turn_id: str,
    phase: str,
    dom_signals: frozenset[str] | None = None,
    text_length: int | None = None,
    text_digest: str | None = None,
) -> ObservationOutcome | None:
    """Advance an ObservationTracker and log any resulting state transition.

    GP46: neither the tracker's internal transitions nor the evidence that
    drove terminal-candidate acceptance were previously observable after the
    fact -- two live incidents persisted truncated/mid-stream output with no
    trace of which indicators the tracker accepted as terminal. Logs only
    metadata (capability flags, dom-signal names, tracker states, text
    LENGTH) -- never prompt/response content -- on every state transition,
    not just the final accept, so a premature-completion recurrence can be
    diagnosed from the gateway process log instead of requiring a live DOM
    catch. Kept outside ObservationTracker itself so the state machine stays
    a pure, independently-testable unit.
    """
    prev_state = tracker.state
    outcome = tracker.advance(observation, now)
    if tracker.state is not prev_state:
        logger.info(
            "gpt-auto observation transition phase=%s state=%s->%s outcome=%s "
            "caps=%s terminal_candidate=%s terminal_verified_ok=%s "
            "text_len=%s text_digest=%s dom_signals=%s candidate_age=%s "
            "candidate_required_stability=%s candidate_saw_generating=%s",
            phase,
            prev_state.value,
            tracker.state.value,
            outcome.value if outcome is not None else None,
            observation.capabilities,
            observation.terminal_candidate,
            observation.terminal_verified_ok,
            text_length,
            text_digest,
            sorted(dom_signals) if dom_signals is not None else None,
            (
                now - tracker.clock.candidate_entered_at
                if tracker.clock.candidate_entered_at is not None
                else None
            ),
            (
                getattr(
                    tracker.policy,
                    "candidate_contradiction_stability_window_seconds",
                    tracker.policy.candidate_stability_window_seconds,
                )
                if tracker.clock.candidate_saw_contradiction
                else tracker.policy.candidate_stability_window_seconds
            ),
            tracker.clock.candidate_saw_contradiction,
            extra={"turn-id": turn_id},
        )
    return outcome


class TurnState(StrEnum):
    PREPARING = "preparing"
    SUBMITTING = "submitting"
    SIDE_EFFECT_ATTEMPTED = "side-effect-attempted"
    SUBMITTED = "submitted"
    AWAITING_RESPONSE = "awaiting-response"
    GENERATING = "generating"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed-out"


class RecoveryDisposition(StrEnum):
    NOT_SUBMITTED = "not-submitted"
    SUBMITTED = "submitted"
    RESPONDING = "responding"
    COMPLETE = "complete"
    AMBIGUOUS = "ambiguous"


_ENGINE = TransitionEngine(
    TransitionConfig(
        transitions={
            "preparing": frozenset({"submitting", "cancelled", "failed"}),
            "submitting": frozenset({"side-effect-attempted", "cancelled", "failed", "timed-out"}),
            "side-effect-attempted": frozenset({"submitted", "cancelled", "failed", "timed-out"}),
            "submitted": frozenset(
                {"awaiting-response", "generating", "complete", "cancelled", "failed", "timed-out"}
            ),
            "awaiting-response": frozenset(
                {"generating", "complete", "cancelled", "failed", "timed-out"}
            ),
            "generating": frozenset({"complete", "cancelled", "failed", "timed-out"}),
        },
        terminal_states=frozenset({"complete", "failed", "cancelled", "timed-out"}),
        values=frozenset(s.value for s in TurnState),
    )
)


@dataclass(frozen=True)
class _SubmissionProofPolicy:
    """ObservationPolicy for the submission-proof phase (GP07).

    start_bound reuses submission_timeout_seconds (did we see ANY sign of
    it at all -- the raw type+send CDP call already has its own separate
    timeout for that operation itself). Everything after start is
    activity-aware: a real new user message resets the clock; a stuck
    generating=True widget alone never does.
    """

    turn_config: Any

    @property
    def start_bound_seconds(self) -> float:
        return self.turn_config.submission_timeout_seconds

    @property
    def progress_lease_seconds(self) -> float:
        return self.turn_config.submission_proof_progress_lease_seconds

    @property
    def soft_grace_cap_seconds(self) -> float:
        return self.turn_config.submission_proof_progress_lease_seconds / 5

    @property
    def candidate_stability_window_seconds(self) -> float:
        return self.turn_config.poll_interval_seconds

    @property
    def candidate_contradiction_stability_window_seconds(self) -> float:
        return self.candidate_stability_window_seconds

    @property
    def candidate_max_verification_window_seconds(self) -> float:
        return max(10.0, self.turn_config.poll_interval_seconds * 10)

    @property
    def suspect_grace_seconds(self) -> float:
        return self.turn_config.submission_proof_progress_lease_seconds / 5

    @property
    def absolute_ceiling_seconds(self) -> float:
        return self.turn_config.submission_proof_absolute_ceiling_seconds


@dataclass(frozen=True)
class _ResponseCompletionPolicy:
    """ObservationPolicy for the response-completion phase (GP07).

    Re-expresses the pre-existing three-timer structure (start/stall/total,
    already fundamentally sound) through the shared engine instead of a
    bespoke inline loop -- and closes a real latent hole the old loop had:
    last_activity_at could be reset by stop-control/streaming/thinking
    widget transitions alone (response-active's any-of), so a flapping
    widget could indefinitely renew the stall clock even after stop-control
    was demoted to advisory for completion detection. Widget transitions
    are SOFT_LIVENESS here -- bounded grace only, never a real reset. A
    config value of 0 means "disabled" (matches the prior semantics);
    mapped to effectively-infinite rather than an instant trigger.
    """

    turn_config: Any

    @staticmethod
    def _or_infinite(value: float) -> float:
        return value if value else float("inf")

    @property
    def start_bound_seconds(self) -> float:
        return self._or_infinite(self.turn_config.response_start_timeout_seconds)

    @property
    def progress_lease_seconds(self) -> float:
        return self._or_infinite(self.turn_config.response_stall_timeout_seconds)

    @property
    def soft_grace_cap_seconds(self) -> float:
        stall = self.turn_config.response_stall_timeout_seconds
        return (stall / 5) if stall else float("inf")

    @property
    def candidate_stability_window_seconds(self) -> float:
        return self.turn_config.response_stability_seconds

    @property
    def candidate_contradiction_stability_window_seconds(self) -> float:
        # SimpleNamespace-based test doubles from older tests do not have the
        # new field; preserving their normal window keeps the seam compatible.
        return getattr(
            self.turn_config,
            "response_generating_override_stability_seconds",
            self.turn_config.response_stability_seconds,
        )

    @property
    def candidate_max_verification_window_seconds(self) -> float:
        stall = self.turn_config.response_stall_timeout_seconds
        configured_override = getattr(
            self.turn_config, "response_generating_override_stability_seconds", None
        )
        override = self.candidate_contradiction_stability_window_seconds
        if not stall and configured_override is None:
            # Compatibility for older test/config objects: with stall
            # detection disabled, the legacy verification ceiling was also
            # unbounded. Real parsed configs always carry the override.
            return float("inf")
        if not stall:
            return max(self.turn_config.response_stability_seconds * 5, override)
        return max(self.turn_config.response_stability_seconds * 5, stall, override)

    @property
    def suspect_grace_seconds(self) -> float:
        stall = self.turn_config.response_stall_timeout_seconds
        return (stall / 5) if stall else float("inf")

    @property
    def absolute_ceiling_seconds(self) -> float:
        return self._or_infinite(self.turn_config.response_timeout_seconds)


class GptAutoTurn:
    def __init__(self, chat: PersistentChat, request: SessionPrompt, sink: ObservationSink) -> None:
        self.chat = chat
        self.request = request
        self.sink = sink
        self.state = TurnState.PREPARING
        self.submission_confirmed = False
        self.side_effect_attempted = False
        self.cancel_event = asyncio.Event()
        self._stop_task: asyncio.Task[None] | None = None
        self._sequence = 0
        self._delivered = 0
        self._phase = "initialization"
        self._composer_verification_mismatch: dict[str, Any] | None = None
        self._prompt_message_id: str | None = None
        self._response_message_id: str | None = None
        self._submission_settled = asyncio.Event()
        self._done = asyncio.Event()
        # Keep the last bounded observation locally so an unprovable provider
        # outcome can fail with evidence instead of a generic explanation.
        # Never retain prompt/response bodies here: IDs, lengths and DOM
        # markers are sufficient to diagnose the boundary safely.
        self._last_snapshot: ChatSnapshot | None = None
        self._last_observation_error: BaseException | None = None
        self._baseline_snapshot: ChatSnapshot | None = None
        self._terminal_evidence: dict[str, Any] = {}

    def _move(self, target: TurnState) -> None:
        failure = _ENGINE.check(self.state.value, target.value)
        if failure:
            raise RuntimeError(f"illegal turn transition {self.state}->{target}: {failure}")
        self.state = target

    async def _emit(self, kind: TransportObservationKind, attributes: dict[str, Any]) -> None:
        value = TransportObservation(
            ag_session_id=self.chat.ag_session_id,
            turn_id=self.request.turn_id,
            sequence=self._sequence,
            kind=kind,
            observed_at=now_iso_z(),
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            attributes=attributes,
        )
        self._sequence += 1
        result = self.sink(value)
        if asyncio.iscoroutine(result):
            await result
        self._delivered += 1

    async def run(self) -> SessionTurnResult:
        self.chat.active_turn_id = self.request.turn_id
        self._set_chat_state(ChatState.BUSY)
        try:
            return await self._run()
        except asyncio.CancelledError:
            if self.side_effect_attempted:
                mark_unresolved = getattr(self.chat, "mark_submission_unresolved", None)
                if mark_unresolved is not None:
                    mark_unresolved(self.request.body)
                if self.chat.state not in {ChatState.CLOSED, ChatState.FAILED, ChatState.RECOVERING}:
                    self._set_chat_state(ChatState.RECOVERING)
            if not _ENGINE.is_terminal(self.state.value):
                self._move(TurnState.CANCELLED)
            raise
        except Exception as exc:
            if not _ENGINE.is_terminal(self.state.value):
                self._move(TurnState.FAILED)
            if self.chat.state not in {ChatState.FAILED, ChatState.CLOSED}:
                self._set_chat_state(ChatState.FAILED)
            if self.side_effect_attempted and not isinstance(exc, AudiaGenticError):
                cause = str(exc).strip() or "no exception message"
                observation_failure = self._phase in {
                    "submission-proof",
                    "turn-accepted-observation",
                    "response-observation",
                    "terminal-observation",
                }
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-004" if observation_failure else "EXT-GPTAUTO-003",
                    kind="providers",
                    message=(
                        "gpt-auto lost deterministic observation during "
                        f"{self._phase}: {type(exc).__name__}: {cause}"
                    ),
                    details={
                        "turn-id": self.request.turn_id,
                        "failure-reason": "unclassified-provider-boundary-exception",
                        "cause-type": type(exc).__name__,
                        "cause-message": cause,
                        "submission-attempted": True,
                        "submission-proven": self.submission_confirmed,
                        **self._diagnostics(),
                    },
                ) from exc
            raise
        finally:
            if self._stop_task is not None:
                await asyncio.gather(self._stop_task, return_exceptions=True)
            self.chat.active_turn_id = None
            if self.chat.state not in {ChatState.FAILED, ChatState.CLOSED, ChatState.RECOVERING}:
                self._set_chat_state(ChatState.READY)
            self._done.set()

    async def wait_done(self, timeout: float) -> None:
        await asyncio.wait_for(self._done.wait(), timeout=timeout)

    async def _run(self) -> SessionTurnResult:
        if self.cancel_event.is_set():
            self._move(TurnState.CANCELLED)
            return self._result("cancelled")
        self._phase = "baseline-observation"
        baseline = await self.chat.snapshot()
        if baseline.generating or not baseline.composer_editable:
            baseline = await self._await_composer_settled(baseline)
        self._baseline_snapshot = baseline
        self._remember_snapshot(baseline)
        self._move(TurnState.SUBMITTING)
        self._phase = "submission"
        mark_unresolved = getattr(self.chat, "mark_submission_unresolved", None)
        if mark_unresolved is not None:
            # Once the browser-side submit call starts, the Send may have
            # reached ChatGPT even if CDP fails before returning a result.
            mark_unresolved(self.request.body)
            if self.chat.provider_session_id:
                await self._publish_message_ids(strict=True)
        persist_checkpoint = getattr(self.chat, "persist_unresolved_checkpoint", None)
        if persist_checkpoint is not None:
            await persist_checkpoint(turn_id=self.request.turn_id, baseline=baseline)
        await self._submit_once()
        if self.state is TurnState.CANCELLED:
            return self._result("cancelled")
        self._phase = "submission-proof"
        proof = await self._await_submission_proof(baseline)
        if proof is None:
            if self.state is TurnState.CANCELLED:
                if self.side_effect_attempted:
                    await self._capture_provider_identity_after_ambiguous_submission()
                return self._result("cancelled")
            # ChatGPT may have created/navigated to the conversation even when
            # the exact prompt proof was not observable before the timeout.
            # Preserve that durable provider URL so a failed keep-alive session
            # can still be resumed later; this does not turn the ambiguous
            # submission into a success.
            await self._capture_provider_identity_after_ambiguous_submission()
            self._move(TurnState.TIMED_OUT)
            raise AudiaGenticError(
                code="EXT-GPTAUTO-003",
                kind="providers",
                message=(
                    "gpt-auto could not prove the submitted prompt: "
                    "submission-proof-not-observed-before-deadline"
                ),
                details={
                    "turn-id": self.request.turn_id,
                    "failure-reason": "submission-proof-not-observed-before-deadline",
                    "submission-ambiguous": True,
                    **self._diagnostics(expected_prompt=self.request.body),
                },
            )
        self.submission_confirmed = True
        if proof.latest_user_id:
            mark_prompt = getattr(self.chat, "mark_prompt_submitted", None)
            if mark_prompt is not None:
                mark_prompt(proof.latest_user_id, baseline.latest_assistant_id, self.request.body)
                persist_checkpoint = getattr(self.chat, "persist_unresolved_checkpoint", None)
                if persist_checkpoint is not None:
                    await persist_checkpoint(turn_id=self.request.turn_id, baseline=baseline)
        self._move(TurnState.SUBMITTED)
        self._phase = "turn-accepted-observation"
        await self._emit(TransportObservationKind.TURN_ACCEPTED, {"reason": "provider-accepted"})
        if self.chat.provider_session_id is None:
            proof = await self.chat.acquire_provider_identity(proof)
        await self._publish_message_ids(strict=True)
        if self.state is TurnState.CANCELLED:
            return self._result("cancelled")
        self._move(TurnState.AWAITING_RESPONSE)
        self._phase = "response-observation"
        final = await self._await_response(baseline, proof)
        if self.state is TurnState.CANCELLED:
            return self._result("cancelled")
        if final is None:
            raise RuntimeError("cancelled response wait returned without cancelled state")
        self._move(TurnState.COMPLETE)
        self._phase = "terminal-observation"
        await self._publish_message_ids(strict=True)
        clear_unresolved = getattr(self.chat, "clear_unresolved_turn", None)
        if clear_unresolved is not None:
            clear_unresolved()
            persist_clear = getattr(self.chat, "persist_unresolved_clear", None)
            if persist_clear is not None:
                await persist_clear()
        await self._emit(TransportObservationKind.TERMINAL, {"stop_reason": "end-turn"})
        result = self._result("end-turn")
        return SessionTurnResult(**{**result.__dict__, "final_summary": final})

    async def _capture_provider_identity_after_ambiguous_submission(self) -> None:
        """Persist a conversation URL observed after an ambiguous submit."""
        try:
            current = await self.chat.snapshot()
            self._remember_snapshot(current)
            is_new = _new_user_message(self._baseline_snapshot, current) if self._baseline_snapshot else True
            if (
                is_new
                and match_prompt(
                    self.request.body, current.latest_user_correlation_text() or ""
                )
                and current.latest_user_id
            ):
                self._prompt_message_id = current.latest_user_id
                mark_prompt = getattr(self.chat, "mark_prompt_submitted", None)
                if mark_prompt is not None:
                    mark_prompt(
                        current.latest_user_id,
                        self._baseline_snapshot.latest_assistant_id
                        if self._baseline_snapshot
                        else None,
                        self.request.body,
                    )
            if self.chat.provider_session_id is None and parse_provider_session_id(current.url):
                await self.chat.acquire_provider_identity(current)
            if self.chat.provider_session_id:
                await self._publish_message_ids(strict=False)
        except Exception as exc:  # noqa: BLE001 - preservation is best effort
            self._last_observation_error = exc
            logger.debug(
                "could not preserve gpt-auto provider identity after ambiguous submission",
                extra={"session-id": self.chat.ag_session_id},
                exc_info=True,
            )

    async def _await_composer_settled(self, current: ChatSnapshot) -> ChatSnapshot:
        """GP11: a turn submitted immediately after the previous one resolves
        can race a composer that has not finished settling (still showing
        generating=True, or composer_editable not yet true again) --
        proven live to cause composer-action-not-confirmed. ensure_ready()
        only re-reconciles a RECOVERING chat; an already-READY chat's
        composer state is never re-verified at admission. Give it a short,
        bounded window to settle here instead. If it never settles within
        the budget, proceed anyway (submit()'s own bounded retry, GP11,
        is the remaining safety net) rather than raise a new failure mode
        for a case that might still succeed."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.chat.config.turn.submission_timeout_seconds
        poll_interval = self.chat.config.turn.poll_interval_seconds or 0.5
        while current.generating or not current.composer_editable:
            if loop.time() >= deadline:
                break
            await asyncio.sleep(poll_interval)
            current = await self.chat.snapshot()
        return current

    async def _submit_once(self) -> None:
        if self.submission_confirmed or self.state is not TurnState.SUBMITTING:
            raise RuntimeError("prompt submission is no longer legal")
        if self.cancel_event.is_set():
            self._move(TurnState.CANCELLED)
            return
        self.side_effect_attempted = True
        try:
            if self.cancel_event.is_set():
                self._move(TurnState.CANCELLED)
                return
            self._move(TurnState.SIDE_EFFECT_ATTEMPTED)
            browser = getattr(self.chat.runtime, "gpt_browser", None)
            if browser is not None:
                page = await browser.page_by_handle(self.chat.page_handle)
                result = await browser.submit(
                    page,
                    self.request.body,
                    timeout=self.chat.config.turn.submission_timeout_seconds,
                )
            else:
                result = await self.chat.runtime.bridge.call(
                    "submit_prompt",
                    {"pageHandle": self.chat.page_handle, "text": self.request.body},
                    timeout=self.chat.config.turn.submission_timeout_seconds,
                )
        except TimeoutError as exc:
            raise AudiaGenticError(
                code="EXT-GPTAUTO-003",
                kind="providers",
                message="gpt-auto composer operation timed out before submission was proven",
                details={
                    "turn-id": self.request.turn_id,
                    "failure-reason": "composer-operation-timeout",
                    "submission-ambiguous": True,
                    **self._diagnostics(expected_prompt=self.request.body),
                },
            ) from exc
        finally:
            self._submission_settled.set()
        typed_text = result.get("typedText") if isinstance(result, dict) else None
        action_complete = result.get("actionComplete") if isinstance(result, dict) else None
        if action_complete is not True:
            enter_dispatched = bool(result.get("enterDispatched")) if isinstance(result, dict) else False
            clear_unresolved = getattr(self.chat, "clear_unresolved_turn", None)
            if clear_unresolved is not None and not enter_dispatched:
                # The browser only entered the text or attempted Enter; it
                # did not attempt a provider submission.  Do not strand the
                # session as unresolved when no provider message could have
                # been sent.
                clear_unresolved()
            raise AudiaGenticError(
                code="EXT-GPTAUTO-003",
                kind="providers",
                message="gpt-auto composer action was not confirmed by the browser",
                details={
                    "turn-id": self.request.turn_id,
                    "failure-reason": "composer-action-not-confirmed",
                    "action-complete": action_complete,
                    "send-button-clicked": result.get("sendButtonClicked")
                    if isinstance(result, dict)
                    else None,
                    "enter-dispatched": result.get("enterDispatched")
                    if isinstance(result, dict)
                    else None,
                    **self._diagnostics(expected_prompt=self.request.body),
                },
            )
        if not match_prompt(self.request.body, str(typed_text or "")):
            # The browser has already reported a completed send action.  The
            # editor's read-back text is only a local pre-flight signal and
            # can differ from the eventual conversation text because React/
            # ProseMirror normalizes whitespace while replacing the composer.
            # Do not retry here: that could duplicate a prompt.  Continue to
            # the authoritative conversation-level proof below; if it cannot
            # prove the exact prompt, the turn remains ambiguous and the
            # unresolved-session barrier prevents another prompt from racing.
            self._composer_verification_mismatch = {
                "failure-reason": "composer-typed-text-mismatch",
                "typed-text-length": len(str(typed_text or "")),
                "typed-text-match": False,
            }
            logger.warning(
                "gpt-auto composer read-back differed; awaiting conversation proof",
                extra={"turn-id": self.request.turn_id},
            )

    async def _await_submission_proof(self, baseline: ChatSnapshot) -> ChatSnapshot | None:
        """GP07: activity-aware, not a single fixed deadline from typing/dispatch.

        A new user message matching the submitted prompt is PROGRESS +
        TERMINAL_WITNESS together (strong, near-instant proof -- no
        multi-second stability dance needed, unlike response text). A new
        message that DOESN'T exactly match (e.g. code-block rendering
        artifacts, GP07 tracked separately) still counts as PROGRESS alone,
        so a real-but-imperfect-match observation correctly resets the
        inactivity clock instead of silently ticking toward a false timeout.
        generating/dom_signals changes are SOFT_LIVENESS only -- bounded
        grace, never authoritative, consistent with the same widget already
        proven unreliable for completion detection.
        """
        turn_cfg = self.chat.config.turn
        policy = _SubmissionProofPolicy(turn_cfg)
        loop = asyncio.get_running_loop()
        tracker = ObservationTracker(policy=policy, now=loop.time())
        expected_fingerprint = PromptFingerprint.from_text(self.request.body)
        # Edge-triggered, not level-triggered: an unchanged fact observed on
        # every poll (e.g. the new user message still being "new" relative
        # to baseline) must not count as PROGRESS again each time -- only a
        # genuine change since the LAST observation does.
        previous_user_id = baseline.latest_user_id
        previous_generating = baseline.generating
        previous_dom_signals = baseline.dom_signals
        previous_assistant_id = baseline.latest_assistant_id
        previous_assistant_text = baseline.latest_assistant_text
        while True:
            if self.cancel_event.is_set():
                self._move(TurnState.CANCELLED)
                return None
            try:
                snap = await self.chat.snapshot()
            except Exception as exc:  # noqa: BLE001 - reconcile after attempted side effect
                self._last_observation_error = exc
                logger.info(
                    "gpt-auto submission proof observation interrupted; awaiting same conversation",
                    extra={"turn-id": self.request.turn_id},
                )
                # A failing observation is not evidence of anything, but the
                # clock must still advance -- otherwise persistent exceptions
                # spin the loop forever with no eventual SUSPECT_STALLED/
                # UNRESOLVED_STALL exit (there is no fixed deadline anymore
                # to fall back on).
                outcome = _advance_with_trace(
                    tracker,
                    Observation(capabilities=EvidenceCapability.NONE, terminal_candidate=False),
                    loop.time(),
                    turn_id=self.request.turn_id,
                    phase="submission-proof",
                )
                if outcome is not None:
                    break
                await asyncio.sleep(self.chat.config.turn.poll_interval_seconds)
                continue
            last_observation_error = None
            self._remember_snapshot(snap)
            new_msg = _new_user_message(baseline, snap)
            text_matches = new_msg and expected_fingerprint.matches_text(
                snap.latest_user_correlation_text() or ""
            )
            user_id_changed = snap.latest_user_id != previous_user_id
            soft_changed = (
                snap.generating != previous_generating or snap.dom_signals != previous_dom_signals
            )
            # GP19: growing assistant output is real evidence the provider is
            # actively working -- unlike a stuck stop-button widget, changing
            # text/id is not something a static DOM state can fake. This is
            # NOT identity proof (a human could also produce this in the same
            # tab, GP08's actor boundary), only activity/progress evidence,
            # so it never sets caps |= TERMINAL_WITNESS on its own.
            assistant_progress = (
                snap.latest_assistant_id != previous_assistant_id
                or snap.latest_assistant_text != previous_assistant_text
            )
            caps = EvidenceCapability.NONE
            if (new_msg and user_id_changed) or assistant_progress:
                caps |= EvidenceCapability.PROGRESS
            # GP19: sustained generating=True is real, ongoing evidence of
            # activity, not just the moment it first became true -- a level
            # check here (not just soft_changed's edge) closes the exact
            # starvation this item was raised for: a prompt match that never
            # succeeds combined with generating=True that never toggles used
            # to leave every subsequent poll with EvidenceCapability.NONE.
            if snap.generating or (soft_changed and snap.dom_signals):
                caps |= EvidenceCapability.SOFT_LIVENESS
            if text_matches:
                caps |= EvidenceCapability.TERMINAL_WITNESS
            observation = Observation(
                capabilities=caps, terminal_candidate=text_matches, terminal_verified_ok=text_matches
            )
            previous_user_id = snap.latest_user_id
            previous_generating = snap.generating
            previous_dom_signals = snap.dom_signals
            previous_assistant_id = snap.latest_assistant_id
            previous_assistant_text = snap.latest_assistant_text
            if text_matches:
                self._prompt_message_id = snap.latest_user_id
            outcome = _advance_with_trace(
                tracker,
                observation,
                loop.time(),
                turn_id=self.request.turn_id,
                phase="submission-proof",
                dom_signals=snap.dom_signals,
                text_length=len(snap.latest_user_text or ""),
            )
            if outcome is ObservationOutcome.VERIFIED_TERMINAL:
                return snap
            if outcome is not None:
                break
            finder = getattr(self.chat, "find_prompt_snapshot", None)
            if finder is not None:
                alternate = await finder(baseline, self.request.body)
                if alternate is not None:
                    self._prompt_message_id = alternate.latest_user_id
                    return alternate
            await asyncio.sleep(0.2)
        if last_observation_error is not None:
            raise AudiaGenticError(
                code="EXT-GPTAUTO-004",
                kind="providers",
                message=(
                    "gpt-auto could not observe submission proof: "
                    f"{type(last_observation_error).__name__}: {last_observation_error}"
                ),
                details={
                    "turn-id": self.request.turn_id,
                    "phase": "submission-proof",
                    "failure-reason": "submission-proof-observation-failed",
                    "cause-type": type(last_observation_error).__name__,
                    "cause-message": str(last_observation_error),
                    "submission-ambiguous": True,
                    **self._diagnostics(expected_prompt=self.request.body),
                },
            ) from last_observation_error
        return None

    _SOFT_LIVENESS_SIGNALS = frozenset(
        {"stop-control", "streaming-indicator", "thinking-indicator", "busy-indicator"}
    )
    # Renderer-position DOM markers (data-is-last-node/data-is-only-node)
    # describe the last node rendered so far, not the end of the provider
    # turn. They have appeared while substantial output was still streaming,
    # so they are never terminal witnesses. The action-bar pair below is the
    # only standard-bubble terminal witness set.
    #
    # GP34/code review: canvas-edit-control/canvas-open-editor-control are
    # deliberately NOT included, even though they cover ChatGPT's canvas
    # response variant elsewhere (response-complete's second any-of-groups
    # entry) -- code review confirmed live that either one ALONE (or even
    # both together, without the not-generating fact response-complete
    # also requires for that group) is not a valid terminal witness, since
    # both were observed to appear at canvas-panel-CREATION time, not at
    # completion. A single-signal OR-set like this one cannot express
    # "both plus not currently generating", so canvas completion is left
    # entirely to response-complete's own properly-guarded group instead
    # of being approximated here.
    _TERMINAL_WITNESS_SIGNALS = frozenset({"completion-control", "more-actions-menu"})
    # GP47: cadence for the poll-loop heartbeat log, independent of tracker
    # state transitions -- see _await_response's heartbeat comment.
    _HEARTBEAT_INTERVAL_SECONDS = 30.0
    # A tool/app row can remain visible with the same count for a long time
    # while the provider is still working. Edge-only detection then stops
    # renewing the gateway lease even though the browser is visibly busy.
    _TOOL_ACTIVITY_HEARTBEAT_INTERVAL_SECONDS = 5.0

    async def _await_response(self, baseline: ChatSnapshot, current: ChatSnapshot) -> str | None:
        """GP07: re-expresses the previously-bespoke start/stall/total timer
        loop through the shared observation engine. Closes a real latent
        hole the old loop had: last_activity_at could be reset by
        stop-control/streaming/thinking widget transitions ALONE
        (response-active's any-of), so a flapping widget could indefinitely
        renew the stall clock even after stop-control was demoted to
        advisory for completion detection itself. Widget transitions are
        SOFT_LIVENESS now -- bounded grace, never a real reset.
        """
        loop = asyncio.get_running_loop()
        policy = _ResponseCompletionPolicy(self.chat.config.turn)
        tracker = ObservationTracker(policy=policy, now=loop.time())
        # GP30: correlate against THIS request's own prompt anchor, not
        # whatever is conversation-global-latest -- prevents a later,
        # unrelated turn's response (from any actor) from ever being
        # mistaken for this request's own answer.
        prompt_message_id = self._prompt_message_id
        previous = current
        response_started = False
        emitted = False
        final_outcome: ObservationOutcome | None = None
        # GP47 (2026-08-19): _advance_with_trace only logs on a tracker STATE
        # TRANSITION. A turn that stalls for the full response-total-timeout
        # (observed live: completion evidence present but never promoted past
        # candidacy) can spend up to an hour with zero transitions and
        # therefore zero log lines -- the only evidence surviving to the
        # failure report was a single final snapshot, not enough to tell
        # whether `generating` was wrongly stuck true throughout, or whether
        # completion evidence itself simply never appeared until too late.
        # A coarse heartbeat, independent of transitions, makes a future
        # stall's timeline reconstructable from the gateway process log.
        last_heartbeat_at = loop.time()
        last_tool_activity_emit_at = (
            loop.time() - self._TOOL_ACTIVITY_HEARTBEAT_INTERVAL_SECONDS
        )
        while True:
            if self.cancel_event.is_set():
                if self._stop_task is None:
                    self._stop_task = asyncio.create_task(self._stop_generation_best_effort())
                await asyncio.gather(self._stop_task, return_exceptions=True)
                self._move(TurnState.CANCELLED)
                return None
            try:
                raw_current = await self.chat.snapshot()
            except Exception as exc:  # noqa: BLE001 - never re-submit after an attempted send
                self._last_observation_error = exc
                logger.info(
                    "gpt-auto response observation interrupted; awaiting conversation recovery",
                    extra={"turn-id": self.request.turn_id},
                )
                outcome = _advance_with_trace(
                    tracker,
                    Observation(capabilities=EvidenceCapability.NONE, terminal_candidate=False),
                    loop.time(),
                    turn_id=self.request.turn_id,
                    phase="response-complete",
                )
                if outcome is not None:
                    final_outcome = outcome
                    break
                await asyncio.sleep(self.chat.config.turn.poll_interval_seconds)
                continue
            self._remember_snapshot(raw_current)
            if prompt_message_id:
                current, response_ref = _scope_response_snapshot(
                    baseline, raw_current, prompt_message_id=prompt_message_id
                )
            else:
                # Defensive fallback only -- _await_submission_proof() and
                # its duplicate-tab finder fallback always set this before
                # _await_response() can be reached.
                current, response_ref = raw_current, None
            now = loop.time()
            if response_ref is not None and response_ref.message_id:
                if self._response_message_id is None:
                    self._response_message_id = response_ref.message_id
                    mark_assistant = getattr(self.chat, "mark_assistant_observed", None)
                    if mark_assistant is not None:
                        mark_assistant(response_ref.message_id)
                    await self._publish_message_ids(strict=True)
                elif self._response_message_id != response_ref.message_id:
                    # Never silently "follow latest" once an identity is
                    # established -- a later, unrelated turn's assistant
                    # message must never overwrite this request's own.
                    raise AudiaGenticError(
                        code="EXT-GPTAUTO-004",
                        kind="providers",
                        message="gpt-auto observed a conflicting response correlation",
                        details={
                            "turn-id": self.request.turn_id,
                            "failure-reason": "frozen-response-correlation-conflict",
                            "expected-assistant-id": self._response_message_id,
                            "observed-assistant-id": response_ref.message_id,
                            **self._diagnostics(),
                        },
                    )
            facts = _facts(baseline, previous, current)
            failed = self.chat.config.workflow.policy("response-failed").evaluate(facts)
            if failed.satisfied:
                logger.warning(
                    "gpt-auto response failure policy matched",
                    extra={"turn-id": self.request.turn_id, "evidence": sorted(failed.matched)},
                )
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-003",
                    kind="providers",
                    message=(
                        "gpt-auto provider failure policy matched: "
                        + ",".join(sorted(failed.matched))
                    ),
                    details={
                        "turn-id": self.request.turn_id,
                        "failure-reason": "provider-failure-policy-matched",
                        "evidence": sorted(failed.matched),
                        **self._diagnostics(),
                    },
                )
            started = self.chat.config.workflow.policy("response-started").evaluate(facts)
            if started.satisfied and not response_started:
                response_started = True
                logger.info(
                    "gpt-auto response-started policy matched evidence=%s",
                    sorted(started.matched),
                )
                self._move(TurnState.GENERATING)
                await self._emit(
                    TransportObservationKind.IN_PROGRESS,
                    {"model_activity": "response-started"},
                )
                emitted = True
            complete = self.chat.config.workflow.policy("response-complete").evaluate(facts)
            if complete.satisfied and current.generating:
                # stop-control (the usual source of a raw .generating=True)
                # is proven live-unreliable -- it can stick indefinitely
                # after real completion. It is advisory-only now: logged
                # when it disagrees with the response-complete policy
                # (which already requires corroborating any-of evidence
                # plus the text-stability window below), never a veto.
                logger.warning(
                    "gpt-auto Tier-3 generating signal disagreed with "
                    "response-complete policy evidence=%s",
                    sorted(complete.matched),
                    extra={"turn-id": self.request.turn_id},
                )
            if now - last_heartbeat_at >= self._HEARTBEAT_INTERVAL_SECONDS:
                last_heartbeat_at = now
                logger.info(
                    "gpt-auto response poll heartbeat tracker_state=%s generating=%s "
                    "complete_satisfied=%s complete_evidence=%s text_len=%d "
                    "text_digest=%s dom_signals=%s",
                    tracker.state.value,
                    current.generating,
                    complete.satisfied,
                    sorted(complete.matched),
                    len(current.latest_assistant_text or ""),
                    _text_digest(current.latest_assistant_text),
                    sorted(current.dom_signals),
                    extra={"turn-id": self.request.turn_id},
                )

            tool_activity_edge = current.tool_activity_counts != previous.tool_activity_counts
            # Tool rows remain in the completed assistant turn's DOM. Treat
            # their presence as liveness only until the completion policy is
            # satisfied, then stop heartbeating so terminal stability can
            # still be proven.
            active_tool_activity = bool(current.tool_activity_counts) and not complete.satisfied
            tool_activity_heartbeat_due = (
                active_tool_activity
                and now - last_tool_activity_emit_at
                >= self._TOOL_ACTIVITY_HEARTBEAT_INTERVAL_SECONDS
            )
            progress_edge = (
                current.latest_assistant_id != previous.latest_assistant_id
                or current.latest_assistant_text != previous.latest_assistant_text
                or current.assistant_count != previous.assistant_count
                or current.user_count != previous.user_count
                or current.assistant_message_ids != previous.assistant_message_ids
                or current.user_message_ids != previous.user_message_ids
                or tool_activity_edge
            )
            current_soft = current.dom_signals & self._SOFT_LIVENESS_SIGNALS
            previous_soft = previous.dom_signals & self._SOFT_LIVENESS_SIGNALS
            soft_edge = current_soft != previous_soft or current.generating != previous.generating
            soft_present = bool(current_soft) or current.generating
            caps = EvidenceCapability.NONE
            if response_started and progress_edge:
                caps |= EvidenceCapability.PROGRESS
            elif tool_activity_edge or tool_activity_heartbeat_due:
                # A verified current-turn tool/app affordance is strong
                # provider progress even before assistant text begins. Once
                # the row's count stops changing, the bounded heartbeat keeps
                # the provider lease alive without treating DOM leftovers as
                # terminal evidence.
                caps |= EvidenceCapability.PROGRESS
            if response_started and soft_edge and soft_present:
                caps |= EvidenceCapability.SOFT_LIVENESS
            if current.dom_signals & self._TERMINAL_WITNESS_SIGNALS:
                caps |= EvidenceCapability.TERMINAL_WITNESS
            if caps & (EvidenceCapability.PROGRESS | EvidenceCapability.SOFT_LIVENESS):
                # Edge-triggered by construction (progress_edge/soft_edge
                # already compare against the previous observation), so this
                # fires every time real activity is newly observed -- not
                # just once -- matching the pre-existing behavior. The
                # gateway's own watchdog activity lease depends on these
                # ACTIVITY emissions arriving throughout the turn, not just
                # at the start.
                activity_label = (
                    "tool-progress"
                    if tool_activity_edge or tool_activity_heartbeat_due
                    else (
                        "response-progress"
                        if EvidenceCapability.PROGRESS in caps
                        else "soft-liveness"
                    )
                )
                await self._emit(
                    TransportObservationKind.ACTIVITY,
                    {"model_activity": activity_label},
                )
                if tool_activity_edge or tool_activity_heartbeat_due:
                    last_tool_activity_emit_at = now
                emitted = True

            terminal_candidate = complete.satisfied and bool(current.latest_assistant_text)
            terminal_verified_ok = False
            response_message_id = current.latest_assistant_id
            response_text = current.latest_assistant_text
            if terminal_candidate and tracker.state.value != "candidate-terminal":
                logger.info(
                    "gpt-auto response terminal-candidate evidence=%s text_len=%d "
                    "text_digest=%s generating=%s required_stability=%s dom_signals=%s",
                    sorted(complete.matched),
                    len(response_text or ""),
                    _text_digest(response_text),
                    current.generating,
                    (
                        policy.candidate_contradiction_stability_window_seconds
                        if current.generating
                        else policy.candidate_stability_window_seconds
                    ),
                    sorted(current.dom_signals),
                    extra={"turn-id": self.request.turn_id},
                )
            if terminal_candidate and not emitted:
                await self._emit(
                    TransportObservationKind.ACTIVITY, {"model_activity": "response-observed"}
                )
                emitted = True
            if (
                terminal_candidate
                and tracker.state.value == "candidate-terminal"
                and tracker.clock.candidate_entered_at is not None
                and now - tracker.clock.candidate_entered_at
                >= policy.candidate_stability_window_seconds
            ):
                # An independent, freshly-fetched snapshot -- not just the
                # same regular poll cadence -- confirms the candidate before
                # it is trusted, matching the pre-existing design.
                try:
                    raw_verify = await self.chat.snapshot()
                except Exception as exc:  # noqa: BLE001 - verification resumes on next poll
                    self._last_observation_error = exc
                    logger.info(
                        "gpt-auto terminal verification observation interrupted; retrying",
                        extra={"turn-id": self.request.turn_id},
                    )
                    outcome = _advance_with_trace(
                        tracker,
                        Observation(capabilities=caps, terminal_candidate=terminal_candidate),
                        loop.time(),
                        turn_id=self.request.turn_id,
                        phase="response-complete",
                        dom_signals=current.dom_signals,
                        text_length=len(current.latest_assistant_text or ""),
                    )
                    if outcome is not None:
                        final_outcome = outcome
                        break
                    await asyncio.sleep(self.chat.config.turn.poll_interval_seconds)
                    continue
                self._remember_snapshot(raw_verify)
                if prompt_message_id:
                    verify, _verify_ref = _scope_response_snapshot(
                        baseline, raw_verify, prompt_message_id=prompt_message_id
                    )
                else:
                    verify = raw_verify
                verify_facts = _facts(baseline, current, verify)
                verified = self.chat.config.workflow.policy("response-complete").evaluate(
                    verify_facts
                )
                if verify.generating:
                    logger.warning(
                        "gpt-auto Tier-3 generating signal disagreed with "
                        "response-complete policy at final verification evidence=%s",
                        sorted(verified.matched),
                        extra={"turn-id": self.request.turn_id},
                    )
                terminal_verified_ok = (
                    verified.satisfied and verify.latest_assistant_text == current.latest_assistant_text
                )
                response_message_id = verify.latest_assistant_id
                response_text = verify.latest_assistant_text
                logger.info(
                    "gpt-auto response completion verification result=%s evidence=%s "
                    "candidate_text_len=%d candidate_text_digest=%s "
                    "verify_text_len=%d verify_text_digest=%s generating=%s "
                    "candidate_age=%.3f required_stability=%s dom_signals=%s",
                    terminal_verified_ok,
                    sorted(verified.matched),
                    len(current.latest_assistant_text or ""),
                    _text_digest(current.latest_assistant_text),
                    len(response_text or ""),
                    _text_digest(response_text),
                    verify.generating,
                    (
                        loop.time() - tracker.clock.candidate_entered_at
                        if tracker.clock.candidate_entered_at is not None
                        else -1.0
                    ),
                    (
                        policy.candidate_contradiction_stability_window_seconds
                        if tracker.clock.candidate_saw_contradiction
                        else policy.candidate_stability_window_seconds
                    ),
                    sorted(verify.dom_signals),
                    extra={"turn-id": self.request.turn_id},
                )

            observation = Observation(
                capabilities=caps,
                terminal_candidate=terminal_candidate,
                terminal_verified_ok=terminal_verified_ok,
                terminal_contradiction=terminal_candidate and current.generating,
            )
            outcome = _advance_with_trace(
                tracker,
                observation,
                loop.time(),
                turn_id=self.request.turn_id,
                phase="response-complete",
                dom_signals=current.dom_signals,
                text_length=len(response_text or ""),
                text_digest=_text_digest(response_text),
            )
            if outcome is ObservationOutcome.VERIFIED_TERMINAL:
                assert response_text is not None
                self._response_message_id = response_message_id
                self._terminal_evidence = {
                    "policy": "response-complete",
                    "generating-at-terminal": bool(current.generating or verify.generating)
                    if "verify" in locals()
                    else bool(current.generating),
                    "candidate-stability-seconds": round(
                        loop.time() - tracker.clock.candidate_entered_at, 3
                    )
                    if tracker.clock.candidate_entered_at is not None
                    else None,
                    "required-stability-seconds": (
                        policy.candidate_contradiction_stability_window_seconds
                        if tracker.clock.candidate_saw_contradiction
                        else policy.candidate_stability_window_seconds
                    ),
                    "text-length": len(response_text),
                    "text-digest": _text_digest(response_text),
                    "verification-evidence": sorted(verified.matched)
                    if "verified" in locals()
                    else [],
                }
                return response_text
            if outcome is not None:
                final_outcome = outcome
                break
            previous = current
            await asyncio.sleep(self.chat.config.turn.poll_interval_seconds)
        if not response_started:
            self._raise_response_timeout("response-start-timeout")
        elif final_outcome is ObservationOutcome.BUDGET_EXHAUSTED:
            self._raise_response_timeout("response-total-timeout")
        else:
            self._raise_response_timeout("response-stall-timeout")

    def _raise_response_timeout(self, policy: str) -> None:
        self._move(TurnState.TIMED_OUT)
        raise AudiaGenticError(
            code="EXT-GPTAUTO-002",
            kind="providers",
            message=f"gpt-auto response policy timed out: {policy}",
            details={
                "turn-id": self.request.turn_id,
                "failure-reason": "response-policy-timeout",
                "timeout-policy": policy,
                "submission-confirmed": True,
                **self._diagnostics(),
            },
        )

    def cancel(self) -> None:
        self.cancel_event.set()
        # Cancellation is synchronous at the transport boundary.  Schedule
        # the browser-side stop immediately so a generation is interrupted
        # even while submission/proof polling is in progress.
        if self._stop_task is None or self._stop_task.done():
            self._stop_task = asyncio.create_task(self._stop_generation_best_effort())

    async def _stop_generation_best_effort(self) -> None:
        stopped = False
        if (
            self.side_effect_attempted
            and self.state in {TurnState.SUBMITTING, TurnState.SIDE_EFFECT_ATTEMPTED}
            and not self._submission_settled.is_set()
        ):
            try:
                await asyncio.wait_for(
                    self._submission_settled.wait(),
                    timeout=self.chat.config.turn.submission_timeout_seconds + 0.5,
                )
            except TimeoutError:
                logger.warning(
                    "gpt-auto cancellation could not await submission settlement",
                    extra={"turn-id": self.request.turn_id},
                )
                if self.chat.state is not ChatState.CLOSED:
                    self._set_chat_state(ChatState.RECOVERING)
                return
        try:
            browser = getattr(self.chat.runtime, "gpt_browser", None)
            if browser is not None:
                page = await browser.page_by_handle(self.chat.page_handle)
                result = await browser.stop_generation(page)
                stopped = bool(result.get("stopped")) if isinstance(result, dict) else bool(result)
            else:
                result = await self.chat.runtime.bridge.call(
                    "stop_generation", {"pageHandle": self.chat.page_handle}
                )
                stopped = bool(result.get("stopped")) if isinstance(result, dict) else bool(result)
        except Exception:  # noqa: BLE001 - cancellation must remain best effort
            logger.debug(
                "gpt-auto stop control could not be clicked during cancellation",
                extra={"turn-id": self.request.turn_id},
                exc_info=True,
            )
        if not self.side_effect_attempted:
            return
        try:
            if not stopped:
                raise RuntimeError("provider stop control was not confirmed")
            await self.chat.wait_quiescent()
            clear_unresolved = getattr(self.chat, "clear_unresolved_turn", None)
            if clear_unresolved is not None:
                clear_unresolved()
        except Exception:  # noqa: BLE001 - uncertainty must block the next prompt
            if self.chat.state not in {ChatState.CLOSED, ChatState.FAILED, ChatState.RECOVERING}:
                self._set_chat_state(ChatState.RECOVERING)
            logger.warning(
                "gpt-auto cancellation did not prove provider quiescence",
                extra={"turn-id": self.request.turn_id, "stop-executed": stopped},
            )

    def _set_chat_state(self, state: ChatState) -> None:
        move = getattr(self.chat, "_move", None)
        if move is None:
            self.chat.state = state
        else:
            move(state)

    def _remember_snapshot(self, snapshot: ChatSnapshot) -> None:
        self._last_snapshot = snapshot
        self._last_observation_error = None

    def _diagnostics(self, *, expected_prompt: str | None = None) -> dict[str, Any]:
        """Return bounded, sparse evidence for a provider-boundary failure."""
        details: dict[str, Any] = {
            "phase": self._phase,
            "turn-state": self.state.value,
            "chat-state": self.chat.state.value,
            "page-handle": self.chat.page_handle,
            "target-id": getattr(self.chat, "target_id", None),
            "provider-session-id": self.chat.provider_session_id,
            **_message_ids(self),
        }
        if self._composer_verification_mismatch:
            details.update(self._composer_verification_mismatch)
        snapshot = self._last_snapshot
        if snapshot is not None:
            details.update(_snapshot_diagnostics(snapshot, expected_prompt=expected_prompt))
        error = self._last_observation_error
        if error is not None:
            details.update(
                {
                    "last-observation-error-type": type(error).__name__,
                    "last-observation-error": str(error),
                }
            )
        return {key: value for key, value in details.items() if value is not None and value != ""}

    def _result(self, reason: str) -> SessionTurnResult:
        metadata: dict[str, Any] = {"project-url": self.chat.project_url}
        if self.chat.provider_session_id:
            metadata.update(
                {
                    "provider-session-id": self.chat.provider_session_id,
                    "chat-url": self.chat.chat_url,
                }
            )
        metadata.update(_message_ids(self))
        unresolved_metadata = getattr(self.chat, "unresolved_metadata", None)
        if unresolved_metadata is not None:
            metadata.update(unresolved_metadata())
        if self._terminal_evidence:
            metadata["terminal-evidence"] = dict(self._terminal_evidence)
        return SessionTurnResult(
            turn_id=self.request.turn_id,
            stop_reason=reason,
            observations_delivered=self._delivered,
            dropped_observations=0,
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            metadata=metadata,
        )

    async def _publish_message_ids(self, *, strict: bool = False) -> None:
        """Persist proven prompt identity before response observation begins."""
        if not self.chat.provider_session_id:
            return
        metadata = _message_ids(self)
        unresolved_metadata = getattr(self.chat, "unresolved_metadata", None)
        if unresolved_metadata is not None:
            metadata.update(unresolved_metadata())
        if not metadata:
            return
        try:
            update = ProviderSessionBindingUpdate(
                provider_session_ref=ProviderSessionRef(self.chat.provider_session_id),
                metadata=metadata,
            )
            sink = getattr(self.chat, "binding_sink", None)
            if sink is None:
                return
            result = sink(update)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001 - durable identity is required after proof
            if strict:
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-004",
                    kind="providers",
                    message=(
                        "gpt-auto could not durably persist provider message identity "
                        f"during {self._phase}"
                    ),
                    details={
                        "turn-id": self.request.turn_id,
                        "phase": self._phase,
                        "failure-reason": "provider-message-identity-persistence-failed",
                        "cause-type": type(exc).__name__,
                        "cause-message": str(exc),
                        **self._diagnostics(),
                    },
                ) from exc
            logger.warning(
                "gpt-auto could not persist provider message identity",
                extra={"turn-id": self.request.turn_id},
                exc_info=True,
            )


def _new_user_message(baseline: ChatSnapshot, current: ChatSnapshot) -> bool:
    """Prefer the provider message UUID; counts remain a compatibility fallback."""
    if current.latest_user_id and current.latest_user_id not in set(baseline.user_message_ids):
        return True
    return current.user_count > baseline.user_count


def _response_ref_for_prompt(
    snapshot: ChatSnapshot, prompt_message_id: str
) -> ChatMessageRef | None:
    """GP30: the first assistant message after this request's own prompt,
    before the next user message of any provenance.

    "Latest assistant" alone cannot answer "what was the response to THIS
    request" once a later, unrelated turn (from any actor -- a human typing
    in the same tab, or a later gateway request) has entered the same
    conversation. A hard boundary at the next user message means a later
    turn's assistant reply can never be mistaken for this one's, even once
    it becomes conversation-global-latest.
    """
    refs = snapshot.message_refs
    prompt_index = next(
        (
            index
            for index, ref in enumerate(refs)
            if ref.role == "user" and ref.message_id == prompt_message_id
        ),
        None,
    )
    if prompt_index is None:
        return None
    for ref in refs[prompt_index + 1 :]:
        if ref.role == "user":
            return None
        if ref.role == "assistant":
            return ref
    return None


def _scope_response_snapshot(
    baseline: ChatSnapshot, snapshot: ChatSnapshot, *, prompt_message_id: str
) -> tuple[ChatSnapshot, ChatMessageRef | None]:
    """Project a raw snapshot onto this request's own response, not
    whatever is conversation-global-latest.

    dom_signals/generating are left untouched -- those describe genuine
    page-wide activity/liveness and must keep reflecting reality; only the
    assistant identity/text facts the response-completion policies key off
    of are re-pointed at this request's own span.
    """
    response_ref = _response_ref_for_prompt(snapshot, prompt_message_id)
    if response_ref is None:
        return (
            replace(
                snapshot,
                latest_assistant_id=baseline.latest_assistant_id,
                latest_assistant_text=baseline.latest_assistant_text,
            ),
            None,
        )
    return (
        replace(
            snapshot,
            latest_assistant_id=response_ref.message_id,
            latest_assistant_text=response_ref.text,
        ),
        response_ref,
    )


def _facts(
    baseline: ChatSnapshot, previous: ChatSnapshot, current: ChatSnapshot
) -> dict[str, bool]:
    observation = current.observe(baseline=baseline, previous=previous)
    facts = {name: True for name in observation.markers}
    facts.update(
        {
            "assistant-fresh": "assistant-fresh" in observation.markers,
            "text-present": bool(current.latest_assistant_text),
            "text-changed": "text-changed" in observation.markers,
            "composer-present": current.composer_present,
            "composer-editable": current.composer_editable,
            "composer-unavailable": not current.composer_present or not current.composer_editable,
            # GP34 code-review follow-up: see config.py's known_facts
            # comment for why this exists (a stop-control-free way to gate
            # on "nothing looks actively busy right now").
            "not-generating": not current.generating,
            "page-ready": observation.state.value == "ready",
            "page-submitting": observation.state.value == "submitting",
            "page-generating": observation.state.value == "generating",
            "page-awaiting-completion": observation.state.value == "awaiting-completion",
            "page-completed": observation.state.value == "completed",
            "page-failed": observation.state.value == "failed",
        }
    )
    return facts


def _message_ids(turn: GptAutoTurn) -> dict[str, str]:
    """Return only proven provider message IDs for durable turn metadata."""
    values = {
        "prompt-message-id": turn._prompt_message_id,
        "assistant-message-id": turn._response_message_id,
        "assistant-before-message-id": getattr(
            turn.chat, "unresolved_assistant_before_id", None
        ),
    }
    return {key: value for key, value in values.items() if value}


def _snapshot_diagnostics(
    snapshot: ChatSnapshot, *, expected_prompt: str | None = None
) -> dict[str, Any]:
    """Project bounded DOM evidence into a provider-boundary failure."""
    observation = snapshot.observe()
    result: dict[str, Any] = {
        "observed-url": snapshot.url,
        "observation-state": observation.state.value,
        "observed-user-count": snapshot.user_count,
        "observed-assistant-count": snapshot.assistant_count,
        "composer-present": snapshot.composer_present,
        "composer-editable": snapshot.composer_editable,
        "user-text-present": bool(snapshot.latest_user_text),
        "assistant-text-length": len(snapshot.latest_assistant_text or ""),
    }
    if snapshot.latest_user_id:
        result["observed-user-id"] = snapshot.latest_user_id
    if snapshot.latest_assistant_id:
        result["observed-assistant-id"] = snapshot.latest_assistant_id
    # GP47: previously only included when True, which left a failure
    # report unable to distinguish "not generating" from "not recorded" --
    # exactly the ambiguity that blocked analyzing this class of failure
    # after the fact. Always record the actual value.
    result["generating"] = snapshot.generating
    if snapshot.error_present:
        result["error-present"] = True
    if snapshot.dom_signals:
        result["dom-signals"] = tuple(sorted(snapshot.dom_signals))
    if observation.markers:
        result["observation-markers"] = tuple(sorted(observation.markers))
    if expected_prompt is not None:
        result["expected-prompt-length"] = len(expected_prompt)
        result["observed-user-text-length"] = len(snapshot.latest_user_text or "")
        result["prompt-text-match"] = match_prompt(
            expected_prompt, snapshot.latest_user_text or ""
        )
        correlation_text = snapshot.latest_user_correlation_text()
        if correlation_text and correlation_text != snapshot.latest_user_text:
            result["prompt-correlation-match"] = PromptFingerprint.from_text(
                expected_prompt
            ).matches_text(correlation_text)
            result["prompt-proof-source"] = "gpt-auto-dom-structural-v1"
            result["observed-correlation-text-length"] = len(correlation_text)
            ref = snapshot.latest_user_ref()
            if ref is not None and ref.structural_hr_count:
                result["structural-hr-count"] = ref.structural_hr_count
    return result
