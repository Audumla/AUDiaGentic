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
from audiagentic.foundation.workflow import TransitionConfig, TransitionEngine

from .chat import ChatState, PersistentChat
from .snapshot import ChatSnapshot
from .urls import parse_provider_session_id

logger = logging.getLogger(__name__)


class TurnState(StrEnum):
    PREPARING = "preparing"
    SUBMITTING = "submitting"
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
            "submitting": frozenset({"submitted", "cancelled", "failed", "timed-out"}),
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
        self.cancel_event = asyncio.Event()
        self._sequence = 0
        self._delivered = 0

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
        self.chat.state = ChatState.BUSY
        try:
            return await self._run()
        except asyncio.CancelledError:
            if not _ENGINE.is_terminal(self.state.value):
                self._move(TurnState.CANCELLED)
            return self._result("cancelled")
        except Exception:
            if not _ENGINE.is_terminal(self.state.value):
                self._move(TurnState.FAILED)
            self.chat.state = ChatState.FAILED
            raise
        finally:
            self.chat.active_turn_id = None
            refresh = getattr(self.chat.runtime, "refresh_status_page", None)
            if refresh is not None:
                await refresh()
            if self.chat.state not in {ChatState.FAILED, ChatState.CLOSED, ChatState.RECOVERING}:
                self.chat.state = ChatState.READY

    async def _run(self) -> SessionTurnResult:
        if self.cancel_event.is_set():
            self._move(TurnState.CANCELLED)
            return self._result("cancelled")
        baseline = await self.chat.snapshot()
        self._move(TurnState.SUBMITTING)
        await self._submit_once()
        proof = await self._await_submission_proof(baseline)
        if proof is None:
            if self.state is TurnState.CANCELLED:
                return self._result("cancelled")
            # ChatGPT may have created/navigated to the conversation even when
            # the exact prompt proof was not observable before the timeout.
            # Preserve that durable provider URL so a failed keep-alive session
            # can still be resumed later; this does not turn the ambiguous
            # submission into a success.
            await self._capture_provider_identity_after_ambiguous_submission()
            self._move(TurnState.TIMED_OUT)
            self.chat.state = ChatState.FAILED
            raise AudiaGenticError(
                code="EXT-GPTAUTO-003",
                kind="providers",
                message="gpt-auto could not prove the submitted prompt exactly",
                details={"turn-id": self.request.turn_id, "submission-ambiguous": True},
            )
        self.submission_confirmed = True
        self._move(TurnState.SUBMITTED)
        await self._emit(TransportObservationKind.TURN_ACCEPTED, {"reason": "provider-accepted"})
        if self.chat.provider_session_id is None:
            proof = await self.chat.acquire_provider_identity(proof)
        self._move(TurnState.AWAITING_RESPONSE)
        final = await self._await_response(baseline, proof)
        if self.state is TurnState.CANCELLED:
            return self._result("cancelled")
        if final is None:
            raise RuntimeError("cancelled response wait returned without cancelled state")
        self._move(TurnState.COMPLETE)
        await self._emit(TransportObservationKind.TERMINAL, {"stop_reason": "end-turn"})
        result = self._result("end-turn")
        return SessionTurnResult(**{**result.__dict__, "final_summary": final})

    async def _capture_provider_identity_after_ambiguous_submission(self) -> None:
        """Persist a conversation URL observed after an ambiguous submit."""
        if self.chat.provider_session_id is not None:
            return
        try:
            current = await self.chat.snapshot()
            if parse_provider_session_id(current.url):
                await self.chat.acquire_provider_identity(current)
        except Exception:  # noqa: BLE001 - preservation is best effort
            logger.debug(
                "could not preserve gpt-auto provider identity after ambiguous submission",
                extra={"session-id": self.chat.ag_session_id},
                exc_info=True,
            )

    async def _submit_once(self) -> None:
        if self.submission_confirmed or self.state is not TurnState.SUBMITTING:
            raise RuntimeError("prompt submission is no longer legal")
        try:
            result = await self.chat.runtime.bridge.call(
                "submit_prompt",
                {
                    "pageHandle": self.chat.page_handle,
                    "text": self.request.body,
                    "timeoutMs": int(
                        self.chat.runtime.config.turn.submission_timeout_seconds * 1000
                    ),
                },
                timeout=self.chat.runtime.config.turn.submission_timeout_seconds,
            )
        except TimeoutError as exc:
            raise AudiaGenticError(
                code="EXT-GPTAUTO-003",
                kind="providers",
                message="gpt-auto composer operation timed out before submission was proven",
                details={"turn-id": self.request.turn_id, "submission-ambiguous": True},
            ) from exc
        typed_text = result.get("typedText") if isinstance(result, dict) else None
        if _normal(str(typed_text or "")) != _normal(self.request.body):
            raise AudiaGenticError(
                code="EXT-GPTAUTO-003",
                kind="providers",
                message="gpt-auto composer verification did not match the requested prompt",
                details={"turn-id": self.request.turn_id},
            )

    async def _await_submission_proof(self, baseline: ChatSnapshot) -> ChatSnapshot | None:
        deadline = (
            asyncio.get_running_loop().time()
            + self.chat.runtime.config.turn.submission_timeout_seconds
        )
        expected = _normal(self.request.body)
        while asyncio.get_running_loop().time() < deadline:
            if self.cancel_event.is_set():
                self._move(TurnState.CANCELLED)
                return None
            snap = await self.chat.snapshot()
            if snap.user_count > baseline.user_count and _matches(
                expected, _normal(snap.latest_user_text or "")
            ):
                return snap
            await asyncio.sleep(0.2)
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
        while True:
            if self.cancel_event.is_set():
                try:
                    await self.chat.runtime.bridge.call(
                        "stop_generation", {"pageHandle": self.chat.page_handle}
                    )
                except Exception:
                    pass
                self._move(TurnState.CANCELLED)
                return None
            current = await self.chat.snapshot()
            now = loop.time()
            facts = _facts(baseline, previous, current)
            failed = self.chat.runtime.config.workflow.policy("response-failed").evaluate(facts)
            if failed.satisfied:
                logger.warning(
                    "gpt-auto response failure policy matched",
                    extra={"turn-id": self.request.turn_id, "evidence": sorted(failed.matched)},
                )
                self.chat.state = ChatState.FAILED
                raise AudiaGenticError(
                    code="EXT-GPTAUTO-003",
                    kind="providers",
                    message="ChatGPT DOM reported a failed response state",
                    details={"turn-id": self.request.turn_id, "evidence": sorted(failed.matched)},
                )
            started = self.chat.runtime.config.workflow.policy("response-started").evaluate(facts)
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
            active = self.chat.runtime.config.workflow.policy("response-active").evaluate(facts)
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
            complete = self.chat.runtime.config.workflow.policy("response-complete").evaluate(facts)
            if complete.satisfied and current.latest_assistant_text:
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
                    and now - stable_since
                    >= self.chat.runtime.config.turn.response_stability_seconds
                ):
                    verify = await self.chat.snapshot()
                    verify_facts = _facts(baseline, current, verify)
                    verified = self.chat.runtime.config.workflow.policy(
                        "response-complete"
                    ).evaluate(verify_facts)
                    if verified.satisfied and verify.latest_assistant_text == stable_text:
                        assert stable_text is not None
                        logger.info(
                            "gpt-auto response completion verified evidence=%s chars=%d",
                            sorted(verified.matched),
                            len(stable_text),
                        )
                        return stable_text
            else:
                stable_text = None
                stable_since = None

            timers = self.chat.runtime.config.turn
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
            if timers.response_timeout_seconds and now - started_at >= timers.response_timeout_seconds:
                self._raise_response_timeout("response-total-timeout")
            previous = current
            previous_fingerprint = fingerprint
            await asyncio.sleep(self.chat.runtime.config.turn.poll_interval_seconds)

    def _raise_response_timeout(self, policy: str) -> None:
        self._move(TurnState.TIMED_OUT)
        self.chat.state = ChatState.FAILED
        raise AudiaGenticError(
            code="EXT-GPTAUTO-002",
            kind="providers",
            message="ChatGPT response policy timed out",
            details={
                "turn-id": self.request.turn_id,
                "timeout-policy": policy,
                "submission-confirmed": True,
            },
        )

    def cancel(self) -> None:
        self.cancel_event.set()

    def _result(self, reason: str) -> SessionTurnResult:
        metadata: dict[str, Any] = {"project-url": self.chat.project_url}
        if self.chat.provider_session_id:
            metadata.update(
                {
                    "provider-session-id": self.chat.provider_session_id,
                    "chat-url": self.chat.chat_url,
                }
            )
        return SessionTurnResult(
            turn_id=self.request.turn_id,
            stop_reason=reason,
            observations_delivered=self._delivered,
            dropped_observations=0,
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            metadata=metadata,
        )


def _normal(text: str) -> str:
    return " ".join(text.split()).casefold()


def _matches(expected: str, actual: str) -> bool:
    return expected == actual


def _facts(
    baseline: ChatSnapshot, previous: ChatSnapshot, current: ChatSnapshot
) -> dict[str, bool]:
    assistant_fresh = bool(
        current.latest_assistant_id
        and current.latest_assistant_id != baseline.latest_assistant_id
    )
    facts = {name: True for name in current.dom_signals}
    facts.update(
        {
            "assistant-fresh": assistant_fresh,
            "text-present": bool(current.latest_assistant_text),
            "text-changed": current.latest_assistant_text != previous.latest_assistant_text,
            "composer-present": current.composer_present,
            "composer-editable": current.composer_editable,
            "composer-unavailable": not current.composer_present or not current.composer_editable,
        }
    )
    return facts


def _fingerprint(snapshot: ChatSnapshot) -> tuple[Any, ...]:
    return (
        snapshot.url,
        snapshot.user_count,
        snapshot.assistant_count,
        snapshot.latest_assistant_id,
        snapshot.latest_user_text,
        snapshot.latest_assistant_text,
        snapshot.composer_present,
        snapshot.composer_editable,
        snapshot.dom_signals,
        snapshot.error_present,
    )
