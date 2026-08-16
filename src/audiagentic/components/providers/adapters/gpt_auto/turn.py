"""Explicit gpt-auto turn workflow and no-double-submit boundary."""

from __future__ import annotations

import asyncio
import logging
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
from .snapshot import ChatSnapshot
from .urls import parse_provider_session_id

logger = logging.getLogger(__name__)


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
            refresh = getattr(self.chat.runtime, "refresh_status_page", None)
            if refresh is not None:
                await refresh()
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
                and _matches(_normal(self.request.body), _normal(current.latest_user_text or ""))
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
        if _normal(str(typed_text or "")) != _normal(self.request.body):
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
        deadline = (
            asyncio.get_running_loop().time() + self.chat.config.turn.submission_timeout_seconds
        )
        expected = _normal(self.request.body)
        last_observation_error: BaseException | None = None
        while asyncio.get_running_loop().time() < deadline:
            if self.cancel_event.is_set():
                self._move(TurnState.CANCELLED)
                return None
            try:
                snap = await self.chat.snapshot()
            except Exception as exc:  # noqa: BLE001 - reconcile after attempted side effect
                last_observation_error = exc
                self._last_observation_error = exc
                logger.info(
                    "gpt-auto submission proof observation interrupted; awaiting same conversation",
                    extra={"turn-id": self.request.turn_id},
                )
                await asyncio.sleep(self.chat.config.turn.poll_interval_seconds)
                continue
            last_observation_error = None
            self._remember_snapshot(snap)
            if _new_user_message(baseline, snap) and _matches(
                expected, _normal(snap.latest_user_text or "")
            ):
                self._prompt_message_id = snap.latest_user_id
                return snap
            finder = getattr(self.chat, "find_prompt_snapshot", None)
            if finder is not None:
                alternate = await finder(baseline, expected)
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

    async def _await_response(self, baseline: ChatSnapshot, current: ChatSnapshot) -> str | None:
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        last_activity_at = started_at
        previous = current
        previous_fingerprint = _fingerprint(current)
        response_started = False
        stable_text = None
        stable_since = None
        emitted = False
        last_observation_error: BaseException | None = None
        while True:
            if self.cancel_event.is_set():
                if self._stop_task is None:
                    self._stop_task = asyncio.create_task(self._stop_generation_best_effort())
                await asyncio.gather(self._stop_task, return_exceptions=True)
                self._move(TurnState.CANCELLED)
                return None
            try:
                current = await self.chat.snapshot()
            except Exception as exc:  # noqa: BLE001 - never re-submit after an attempted send
                last_observation_error = exc
                self._last_observation_error = exc
                logger.info(
                    "gpt-auto response observation interrupted; awaiting conversation recovery",
                    extra={"turn-id": self.request.turn_id},
                )
                now = loop.time()
                timers = self.chat.config.turn
                timeout_policy = None
                if not response_started and timers.response_start_timeout_seconds and now - started_at >= timers.response_start_timeout_seconds:
                    timeout_policy = "response-start-observation-timeout"
                elif response_started and timers.response_stall_timeout_seconds and now - last_activity_at >= timers.response_stall_timeout_seconds:
                    timeout_policy = "response-stall-observation-timeout"
                elif timers.response_timeout_seconds and now - started_at >= timers.response_timeout_seconds:
                    timeout_policy = "response-total-observation-timeout"
                if timeout_policy:
                    self._move(TurnState.TIMED_OUT)
                    raise AudiaGenticError(
                        code="EXT-GPTAUTO-004",
                        kind="providers",
                        message=(
                            "gpt-auto response observation failed until "
                            f"{timeout_policy}: {type(exc).__name__}: {exc}"
                        ),
                        details={
                            "turn-id": self.request.turn_id,
                            "phase": "response-observation",
                            "failure-reason": "response-observation-timeout",
                            "timeout-policy": timeout_policy,
                            "cause-type": type(exc).__name__,
                            "cause-message": str(exc),
                            **self._diagnostics(),
                        },
                    ) from exc
                await asyncio.sleep(self.chat.config.turn.poll_interval_seconds)
                continue
            self._remember_snapshot(current)
            now = loop.time()
            if current.latest_assistant_id and current.latest_assistant_id != baseline.latest_assistant_id:
                self._response_message_id = current.latest_assistant_id
                mark_assistant = getattr(self.chat, "mark_assistant_observed", None)
                if mark_assistant is not None:
                    mark_assistant(current.latest_assistant_id)
                await self._publish_message_ids(strict=True)
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
                last_activity_at = now
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
            fingerprint = _fingerprint(current)
            active = self.chat.config.workflow.policy("response-active").evaluate(facts)
            if response_started and active.satisfied and fingerprint != previous_fingerprint:
                last_activity_at = now
                logger.debug(
                    "gpt-auto response activity evidence=%s",
                    sorted(active.matched),
                )
                await self._emit(
                    TransportObservationKind.ACTIVITY,
                    {"model_activity": "response-progress"},
                )
                emitted = True
            complete = self.chat.config.workflow.policy("response-complete").evaluate(facts)
            complete_satisfied = complete.satisfied
            if complete_satisfied and current.generating:
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
                )
            if complete_satisfied and current.latest_assistant_text:
                if not emitted:
                    await self._emit(
                        TransportObservationKind.ACTIVITY,
                        {"model_activity": "response-observed"},
                    )
                    emitted = True
                if current.latest_assistant_text != stable_text:
                    stable_text = current.latest_assistant_text
                    stable_since = now
                    logger.info(
                        "gpt-auto response-complete policy candidate evidence=%s chars=%d",
                        sorted(complete.matched),
                        len(stable_text),
                    )
                elif (
                    stable_since is not None
                    and now - stable_since >= self.chat.config.turn.response_stability_seconds
                ):
                    try:
                        verify = await self.chat.snapshot()
                    except Exception as exc:  # noqa: BLE001 - verification resumes on next poll
                        self._last_observation_error = exc
                        now = loop.time()
                        timers = self.chat.config.turn
                        timeout_policy = None
                        if (
                            response_started
                            and timers.response_stall_timeout_seconds
                            and now - last_activity_at >= timers.response_stall_timeout_seconds
                        ):
                            timeout_policy = "terminal-verification-stall-timeout"
                        elif (
                            timers.response_timeout_seconds
                            and now - started_at >= timers.response_timeout_seconds
                        ):
                            timeout_policy = "terminal-verification-total-timeout"
                        if timeout_policy:
                            self._move(TurnState.TIMED_OUT)
                            raise AudiaGenticError(
                                code="EXT-GPTAUTO-004",
                                kind="providers",
                                message=(
                                    "gpt-auto terminal verification failed until "
                                    f"{timeout_policy}: {type(exc).__name__}: {exc}"
                                ),
                                details={
                                    "turn-id": self.request.turn_id,
                                    "phase": "terminal-verification",
                                    "failure-reason": "terminal-verification-timeout",
                                    "timeout-policy": timeout_policy,
                                    "cause-type": type(exc).__name__,
                                    "cause-message": str(exc),
                                    **self._diagnostics(),
                                },
                            ) from exc
                        await asyncio.sleep(self.chat.config.turn.poll_interval_seconds)
                        continue
                    self._remember_snapshot(verify)
                    verify_facts = _facts(baseline, current, verify)
                    verified = self.chat.config.workflow.policy("response-complete").evaluate(
                        verify_facts
                    )
                    if verify.generating:
                        logger.warning(
                            "gpt-auto Tier-3 generating signal disagreed with "
                            "response-complete policy at final verification evidence=%s",
                            sorted(verified.matched),
                        )
                    if verified.satisfied and verify.latest_assistant_text == stable_text:
                        assert stable_text is not None
                        self._response_message_id = verify.latest_assistant_id
                        logger.info(
                            "gpt-auto response completion verified evidence=%s chars=%d",
                            sorted(verified.matched),
                            len(stable_text),
                        )
                        return stable_text
            else:
                stable_text = None
                stable_since = None

            timers = self.chat.config.turn
            if (
                not response_started
                and timers.response_start_timeout_seconds
                and now - started_at >= timers.response_start_timeout_seconds
            ):
                self._raise_response_timeout("response-start-timeout")
            if (
                response_started
                and timers.response_stall_timeout_seconds
                and now - last_activity_at >= timers.response_stall_timeout_seconds
            ):
                self._raise_response_timeout("response-stall-timeout")
            if (
                timers.response_timeout_seconds
                and now - started_at >= timers.response_timeout_seconds
            ):
                self._raise_response_timeout("response-total-timeout")
            previous = current
            previous_fingerprint = fingerprint
            await asyncio.sleep(self.chat.config.turn.poll_interval_seconds)

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


def _normal(text: str) -> str:
    # Browser text surfaces may normalize line endings and append one terminal
    # newline.  Case, indentation, repeated spaces, and interior blank lines
    # remain semantically significant for coding prompts.
    return text.replace("\r\n", "\n").replace("\r", "\n").removesuffix("\n")


def _matches(expected: str, actual: str) -> bool:
    return expected == actual


def _new_user_message(baseline: ChatSnapshot, current: ChatSnapshot) -> bool:
    """Prefer the provider message UUID; counts remain a compatibility fallback."""
    if current.latest_user_id and current.latest_user_id not in set(baseline.user_message_ids):
        return True
    return current.user_count > baseline.user_count


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
            "page-ready": observation.state.value == "ready",
            "page-submitting": observation.state.value == "submitting",
            "page-generating": observation.state.value == "generating",
            "page-awaiting-completion": observation.state.value == "awaiting-completion",
            "page-completed": observation.state.value == "completed",
            "page-failed": observation.state.value == "failed",
        }
    )
    return facts


def _fingerprint(snapshot: ChatSnapshot) -> tuple[Any, ...]:
    return (
        snapshot.url,
        snapshot.user_count,
        snapshot.assistant_count,
        snapshot.latest_assistant_id,
        snapshot.latest_user_id,
        snapshot.latest_user_text,
        snapshot.latest_assistant_text,
        snapshot.composer_present,
        snapshot.composer_editable,
        snapshot.dom_signals,
        snapshot.error_present,
        snapshot.generating,
    )


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
    if snapshot.generating:
        result["generating"] = True
    if snapshot.error_present:
        result["error-present"] = True
    if snapshot.dom_signals:
        result["dom-signals"] = tuple(sorted(snapshot.dom_signals))
    if observation.markers:
        result["observation-markers"] = tuple(sorted(observation.markers))
    if expected_prompt is not None:
        result["expected-prompt-length"] = len(expected_prompt)
        result["observed-user-text-length"] = len(snapshot.latest_user_text or "")
        result["prompt-text-match"] = _matches(
            _normal(expected_prompt), _normal(snapshot.latest_user_text or "")
        )
    return result
