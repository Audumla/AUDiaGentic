"""AgentSessionTransport for gpt-auto — CDP-connected ChatGPT as a first-class session.

Implements the neutral foundation :class:`AgentSessionTransport` protocol (AS28)
on top of the existing CDP browser-automation pieces (CdpClient, workspace,
prompt_injector, dom_reader, tab_state). One transport owns one CDP helper
process and one mapped ChatGPT workspace tab; closing the session detaches CDP
but never closes the user's browser tab (external browser ownership — there is
no owned child process).

The gateway persists ``str(await transport.open())`` as the provider-session-ref
(AS30 binding) and replays it as ``resume_provider_ref`` on resume (AS49). For
gpt-auto that string is the ChatGPT conversation-id when the active conversation
has one, otherwise the workspace base URL — both are directly resumeable by
:meth:`GptAutoSessionTransport.open`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable

from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.agent_session import (
    ControlDisposition,
    CorrelationQuality,
    ObservationSink,
    SessionControlAction,
    SessionControlRequest,
    SessionControlResult,
    SessionOpenResult,
    SessionPrompt,
    SessionTurnResult,
    TransportObservation,
    TransportObservationKind,
)

from .cdp_client import CdpClient
from .config import GptAutoConfig
from .dom_reader import (
    _get_response_state,
    get_response_text,
    is_generating,
)
from .prompt_injector import (
    inject_prompt,
    wait_for_chatgpt_ready,
)
from .provider import GptAutoError, _resolve_project_name
from .tab_state import update_mapping
from .workspace import (
    WorkspaceInfo,
    ensure_workspace,
    is_in_workspace,
    workspace_base_url,
)

logger = logging.getLogger(__name__)

# Wait budget for a fresh response to begin after submit (mirrors dom_reader).
_START_BUDGET_SECONDS = 15.0

# The streaming indicator (stop button / streaming class) flickers between
# chunks and during the reasoning phase, so a single "not generating" reading
# is not a reliable completion signal. Instead the response is declared
# complete when its text has been unchanged for this full stability window.
_RESPONSE_STABILITY_SECONDS = 6.0

# Click the stop / stop-generating control. Mirrors the detection logic in
# dom_reader._IS_GENERATING_JS so the cancel path stops what it can see.
_STOP_GENERATION_JS = """() => {
    const btn = document.querySelector('[data-testid="stop-generating"]');
    if (btn) { btn.click(); return true; }
    const btns = document.querySelectorAll('button, [role="button"]');
    for (const b of btns) {
        const label = (b.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('stop')) { b.click(); return true; }
    }
    return false;
}"""


class _GptAutoOpenResult(SessionOpenResult):
    """SessionOpenResult whose ``str()`` is the bare provider session ref.

    The gateway persists ``str(await transport.open())`` as the provider-session-ref
    (AS30 binding). The plain dataclass repr must never leak into that binding.
    """

    def __str__(self) -> str:
        return self.ag_session_id


def _conversation_ref_from_url(url: str) -> str:
    """Return the resumeable provider session ref for *url*.

    Prefers the bare conversation-id when the URL carries ``/c/{id}``; otherwise
    the workspace base URL (the ``…/g/g-p-{id}-{slug}`` root). Both are directly
    resumeable by :meth:`GptAutoSessionTransport.open`.
    """
    ws = WorkspaceInfo(name="", url=url)
    conv = ws.conversation_id
    if conv:
        return conv
    base = workspace_base_url(url)
    if is_in_workspace(base):
        return base
    return url


def _normalise_resume_ref(ref: str | None) -> str | None:
    """Reduce a resume ref to the conversation-id shape ``ensure_workspace`` accepts."""
    if not ref:
        return None
    if "/c/" in ref:
        return ref.split("/c/", 1)[1].rstrip("/")
    if ref.startswith("http"):
        # Workspace-base ref — handled separately by _resolve_workspace.
        return None
    return ref


class GptAutoSessionTransport:
    """CDP-backed AgentSessionTransport over an already-running ChatGPT tab.

    Implements the 5-method foundation protocol (AS28) without importing any
    gateway internals. Lifecycle/ownership semantics:

    - ``open()`` finds or reuses the project's workspace tab, waits for ChatGPT
      to be ready, and returns a session id whose ``str()`` is the provider
      session ref (conversation-id when available, else the workspace base URL).
    - ``prompt()`` injects the self-contained prompt into the ProseMirror editor,
      polls the DOM for the response with cooperative cancellation, and delivers
      bounded observations (TURN_ACCEPTED / ACTIVITY / TERMINAL).
    - ``close()`` detaches CDP only — the user's browser tab stays open (external
      browser ownership, no owned child process).
    """

    def __init__(
        self,
        project_root: Path | None = None,
        *,
        config: Any | None = None,
        project_name: str | None = None,
        cdp_url: str = "http://127.0.0.1:9222",
        resume_provider_ref: str | None = None,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._project_root = project_root
        self._config = self._coerce_config(config)
        self._project_name = project_name
        self._cdp_url = cdp_url
        self._resume_provider_ref = resume_provider_ref
        self._client_factory = client_factory or (lambda url: CdpClient(cdp_url=url))
        self._client: Any | None = None
        self._ag_session_id: str | None = None
        self._closed = False
        self._turn_active = False
        self._current_cancel: asyncio.Event | None = None
        self._seq = 0

    @staticmethod
    def _coerce_config(config: Any) -> GptAutoConfig:
        if config is None:
            return GptAutoConfig()
        if isinstance(config, dict):
            return GptAutoConfig.from_dict(config)
        return config

    # ── AgentSessionTransport: open ──────────────────────────────────

    async def open(self) -> SessionOpenResult:
        """Open the session: find/activate the project's workspace tab.

        When constructed with ``resume_provider_ref`` (AS49), reuses that exact
        conversation/workspace ref instead of starting fresh — never both, never
        a silent fallback between the two.
        """
        if self._ag_session_id is not None:
            return _GptAutoOpenResult(ag_session_id=self._ag_session_id)
        if self._closed:
            raise GptAutoError("GptAutoSessionTransport is closed")

        client = self._client_factory(self._cdp_url)
        await client.start()
        self._client = client
        project_name = self._project_name or _resolve_project_name(
            str(self._project_root) if self._project_root is not None else None
        )
        try:
            ws = await self._resolve_workspace(client, project_name)
            if ws is None:
                raise GptAutoError(
                    f"ChatGPT workspace '{project_name}' not found — create it in chatgpt.com first"
                )
            ready = await wait_for_chatgpt_ready(
                client,
                timeout=float(getattr(self._config, "tab_selection_timeout", 15)),
                login_timeout=float(getattr(self._config, "login_timeout", 120)),
            )
            if not ready:
                raise GptAutoError("ChatGPT did not become ready — is the browser logged in?")

            try:
                await client.bring_to_front()
            except Exception:
                logger.debug("bring_to_front failed during open (non-fatal)", exc_info=True)

            ref = _conversation_ref_from_url(ws.url)
            self._ag_session_id = ref
            update_mapping(
                project_name,
                workspace_url=workspace_base_url(ws.url),
                conversation_id=(
                    ref if not ref.startswith("http") and "/c/" not in ref else ""
                ),
                project_root=self._project_root,
            )
            logger.info("gpt-auto session opened (provider-session-ref=%s)", ref)
            return _GptAutoOpenResult(ag_session_id=ref)
        except BaseException:
            self._closed = True
            await self._teardown_client()
            raise

    async def _resolve_workspace(
        self, client: Any, project_name: str
    ) -> WorkspaceInfo | None:
        """Find/activate the project workspace, continuing the resume ref when set."""
        ref = self._resume_provider_ref
        if not ref:
            return await ensure_workspace(
                client, project_name, project_root=self._project_root
            )
        if ref.startswith("http"):
            # Workspace-base (or full conversation) URL — navigate the active tab.
            try:
                await client.evaluate(f'() => {{ window.location.href = "{ref}"; }}')
                for _ in range(40):
                    await asyncio.sleep(0.5)
                    try:
                        url = await client.get_url()
                    except RuntimeError:
                        url = ""
                    if url.startswith(ref) or "/c/" in url:
                        return WorkspaceInfo(name=project_name, url=url)
            except Exception:
                logger.debug("direct navigation to resume ref failed", exc_info=True)
            return WorkspaceInfo(name=project_name, url=ref)
        return await ensure_workspace(
            client,
            project_name,
            conversation_id=_normalise_resume_ref(ref),
            project_root=self._project_root,
        )

    # ── AgentSessionTransport: prompt ────────────────────────────────

    async def prompt(
        self,
        request: SessionPrompt,
        sink: ObservationSink,
    ) -> SessionTurnResult:
        """Run one turn: inject → poll → terminal, with bounded observations."""
        if self._ag_session_id is None or self._client is None:
            raise GptAutoError("GptAutoSessionTransport not opened")
        if self._closed:
            raise GptAutoError("GptAutoSessionTransport is closed")

        turn_id = request.turn_id
        client = self._client
        ag_sid = self._ag_session_id
        cfg = self._config
        delivered = 0
        dropped = 0

        self._current_cancel = asyncio.Event()
        self._turn_active = True

        async def _emit(kind: TransportObservationKind, **attrs: str) -> None:
            nonlocal delivered, dropped
            obs = TransportObservation(
                ag_session_id=ag_sid,
                turn_id=turn_id,
                sequence=self._next_sequence(),
                kind=kind,
                observed_at=now_iso_z(),
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes=attrs,
            )
            try:
                result = sink(obs)
                if asyncio.iscoroutine(result):
                    await result
                delivered += 1
            except Exception:
                dropped += 1

        def _is_cancelled() -> bool:
            if self._current_cancel is not None and self._current_cancel.is_set():
                return True
            if request.cancel_token is not None:
                try:
                    return bool(request.cancel_token.is_set())
                except Exception:
                    pass
            return False

        try:
            if _is_cancelled():
                await _emit(
                    TransportObservationKind.TERMINAL,
                    stop_reason="cancelled",
                )
                return SessionTurnResult(
                    turn_id=turn_id,
                    stop_reason="cancelled",
                    observations_delivered=delivered,
                    dropped_observations=dropped,
                )

            await _emit(
                TransportObservationKind.TURN_ACCEPTED,
                reason="accepted",
            )
            # ChatGPT pauses SSE streaming when the tab is backgrounded or
            # occluded — a backgrounded generation aborts after the first
            # chunk, returning a truncated answer.  Bring the tab to the
            # foreground before injecting so the stream actually completes.
            try:
                await client.bring_to_front()
            except Exception:
                logger.debug("bring_to_front failed (non-fatal)", exc_info=True)
            await inject_prompt(
                client,
                request.body,
                typing_delay=float(getattr(cfg, "typing_speed", 0.03)),
            )
            await _emit(TransportObservationKind.ACTIVITY, model_activity="generating")

            response, cancelled = await self._poll_response(client, cfg, _is_cancelled)

            if cancelled:
                stop_reason = "cancelled"
            elif response:
                stop_reason = "end_turn"
            else:
                stop_reason = "error"

            terminal_attrs: dict[str, str] = {"stop_reason": stop_reason}
            if stop_reason == "error":
                terminal_attrs["error_code"] = "gpt-auto-response-timeout"
            await _emit(TransportObservationKind.TERMINAL, **terminal_attrs)

            return SessionTurnResult(
                turn_id=turn_id,
                stop_reason=stop_reason,
                observations_delivered=delivered,
                dropped_observations=dropped,
                final_summary=response or None,
            )
        finally:
            self._turn_active = False
            self._current_cancel = None

    async def _poll_response(
        self,
        client: Any,
        cfg: GptAutoConfig,
        is_cancelled: Callable[[], bool],
    ) -> tuple[str | None, bool]:
        """Poll the DOM for a response with cooperative cancellation.

        Completion is decided by a **stability window**: the response is
        returned only when its text has been unchanged for a full
        ``_RESPONSE_STABILITY_SECONDS`` window.  The streaming indicator
        (``is_generating``) is not load-bearing for completion because it
        flickers False between streaming chunks and during the reasoning
        phase — a single negative reading would otherwise return a truncated
        answer.  ``is_generating`` is still used only to detect that a fresh
        response has begun.
        """
        base_count, base_text = await _get_response_state(client)
        deadline = time.monotonic() + float(
            getattr(cfg, "response_wait_timeout", 120)
        )
        interval = float(getattr(cfg, "polling_interval", 2.0))
        stability = _RESPONSE_STABILITY_SECONDS
        last_text: str | None = None
        stable_since: float | None = None

        def _is_new(text: str | None) -> bool:
            # baseline_length=0 semantics: any non-empty assistant text counts.
            return bool(text)

        # Wait for the response to start — either a new real assistant block
        # appears (count increases) or ChatGPT begins generating.
        start_deadline = time.monotonic() + _START_BUDGET_SECONDS
        while time.monotonic() < start_deadline:
            if is_cancelled():
                await self._stop_generation(client)
                return None, True
            count, text = await _get_response_state(client)
            if count > base_count or _is_new(text):
                break
            if await is_generating(client):
                break
            await asyncio.sleep(1.0)

        while time.monotonic() < deadline:
            if is_cancelled():
                await self._stop_generation(client)
                break
            count, text = await _get_response_state(client)
            if not (count > base_count or _is_new(text)):
                # Not a fresh response (yet) — no stability can accumulate.
                stable_since = None
                await asyncio.sleep(interval)
                continue
            if text and text != last_text:
                last_text = text
                stable_since = time.monotonic()
                continue
            if text is None:
                # Response block vanished/re-rendered — restart tracking.
                last_text = None
                stable_since = None
                await asyncio.sleep(interval)
                continue

            # Text is unchanged from the previous poll.
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= stability:
                final_text = await get_response_text(client)
                if final_text == last_text:
                    return final_text, False
                if final_text:
                    # Grew again — continue tracking the newer text.
                    last_text = final_text
                    stable_since = time.monotonic()

            await asyncio.sleep(interval)

        return last_text, is_cancelled()

    async def _stop_generation(self, client: Any) -> None:
        try:
            await client.evaluate(_STOP_GENERATION_JS)
        except Exception:
            logger.debug("stop-generation control click failed", exc_info=True)

    # ── AgentSessionTransport: control / close / alive ───────────────

    async def control(
        self,
        request: SessionControlRequest,
    ) -> SessionControlResult:
        """Canonical control with bounded disposition. No native escape hatch."""
        action = request.action

        if action == SessionControlAction.CANCEL_TURN:
            if not self.is_alive():
                return SessionControlResult(
                    disposition=ControlDisposition.UNSUPPORTED,
                )
            if self._current_cancel is not None:
                self._current_cancel.set()
            else:
                # No active turn — a fresh event already set; the next prompt()
                # sees it and returns "cancelled" immediately.
                self._current_cancel = asyncio.Event()
                self._current_cancel.set()
            return SessionControlResult(
                disposition=ControlDisposition.ACCEPTED,
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            )

        if action in (
            SessionControlAction.INTERRUPT_TURN,
            SessionControlAction.STEER_TURN,
        ):
            return SessionControlResult(
                disposition=ControlDisposition.UNSUPPORTED,
                correlation_quality=CorrelationQuality.UNCERTAIN,
            )

        if action == SessionControlAction.RESPOND_PERMISSION:
            # Default-deny: no permission response channel exists for ChatGPT.
            return SessionControlResult(
                disposition=ControlDisposition.UNSUPPORTED,
                correlation_quality=CorrelationQuality.UNCERTAIN,
            )

        if action == SessionControlAction.CLOSE_SESSION:
            await self.close()
            return SessionControlResult(
                disposition=ControlDisposition.ACCEPTED,
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            )

        return SessionControlResult(
            disposition=ControlDisposition.UNSUPPORTED,
        )

    async def close(self) -> None:
        """Shut the session down. Idempotent; never raises.

        Detaches the CDP helper only — the user's ChatGPT browser tab is left
        open (external browser ownership; there is no owned child process).
        """
        if self._closed:
            return
        self._closed = True
        await self._teardown_client()

    def is_alive(self) -> bool:
        return (
            not self._closed
            and self._client is not None
            and self._ag_session_id is not None
        )

    # ── helpers ──────────────────────────────────────────────────────

    async def _teardown_client(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.stop()
            except Exception:
                logger.debug("gpt-auto CDP disconnect failed", exc_info=True)

    def _next_sequence(self) -> int:
        self._seq += 1
        return self._seq


def build_gpt_auto_session_transport(
    project_root: Path,
    *,
    config: Any | None = None,
    project_name: str | None = None,
    resume_provider_ref: str | None = None,
) -> GptAutoSessionTransport:
    """Build a CDP-backed gpt-auto session transport (provider-owned factory).

    Used by ``prepare_provider_session_transport`` for the ``gpt-auto-cdp``
    surface. The transport opens lazily on the first ``open()`` call.
    """
    return GptAutoSessionTransport(
        project_root,
        config=config,
        project_name=project_name,
        resume_provider_ref=resume_provider_ref,
    )


__all__ = ["GptAutoSessionTransport", "build_gpt_auto_session_transport"]
