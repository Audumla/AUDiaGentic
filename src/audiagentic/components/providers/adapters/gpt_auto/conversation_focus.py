"""Strict existing-conversation discovery for the GPT-auto provider."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from audiagentic.components.providers.contracts.conversation_focus import (
    ConversationCaptureLocator,
    ConversationFocusLocator,
    ConversationFocusOutcome,
    ConversationFocusResult,
)
from audiagentic.components.providers.services.config.provider_config import (
    load_provider_config,
)

from .config import GptAutoConfig
from .prompt_fingerprint import PromptFingerprint
from .runtime_registry import get_runtime
from .snapshot import ChatSnapshot
from .urls import canonical_chat_url, parse_project_id, parse_provider_session_id


def _identity_url(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parts = urlsplit(value.strip())
    if not parts.scheme or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, parts.fragment))


def select_focus_page(
    pages: Iterable[Mapping[str, object]],
    locator: ConversationFocusLocator,
) -> tuple[Mapping[str, object] | None, ConversationFocusResult | None]:
    """Select exactly one page using URL/session identity reconciliation.

    The function is pure and intentionally does not expose CDP handles in the
    result.  A caller must activate only the selected page.
    """
    candidates = [p for p in pages if str(p.get("type") or "page") == "page"]
    wanted_project = parse_project_id(locator.project_url or "")
    chat_project = parse_project_id(locator.chat_url or "")
    # Older persisted metadata occasionally carried a project URL from the
    # provider default instead of the project encoded in the durable chat
    # URL.  The chat URL is the stronger request-owned identity (and is also
    # what the browser tab exposes), so repair that stale auxiliary field
    # rather than hiding an otherwise exact retained conversation.
    if wanted_project and chat_project and wanted_project != chat_project:
        wanted_project = chat_project
    if wanted_project:
        candidates = [
            p for p in candidates if parse_project_id(str(p.get("url") or "")) == wanted_project
        ]
    wanted_url = _identity_url(locator.chat_url)
    wanted_session = locator.provider_session_id.strip() if isinstance(locator.provider_session_id, str) and locator.provider_session_id.strip() else None
    url_matches = [p for p in candidates if wanted_url and _identity_url(str(p.get("url") or "")) == wanted_url]
    session_matches = [
        p for p in candidates
        if wanted_session and parse_provider_session_id(str(p.get("url") or "")) == wanted_session
    ]

    def duplicate_result(matches, reason):
        # Physical tabs can duplicate one durable conversation after browser
        # restoration. Only collapse that ambiguity when every canonical
        # project/conversation identity agrees. Capture still proves its turn.
        identities = {canonical_chat_url(str(p.get("url") or "")) for p in matches}
        if len(identities) == 1 and None not in identities:
            preferred = getattr(locator, "provider_target_id", None)
            exact = [p for p in matches if preferred and p.get("targetId") == preferred]
            return min(exact or matches, key=lambda p: str(p.get("targetId") or p.get("pageHandle") or "")), None
        return None, ConversationFocusResult(ConversationFocusOutcome.AMBIGUOUS, reason)

    if wanted_url and wanted_session:
        intersection = [p for p in url_matches if p in session_matches]
        if len(intersection) == 1:
            return intersection[0], None
        if len(intersection) > 1:
            return duplicate_result(intersection, "duplicate-target-identity")
        if url_matches and session_matches:
            return None, ConversationFocusResult(ConversationFocusOutcome.IDENTITY_CONFLICT, "url-session-mismatch")
        if len(session_matches) == 1:
            return session_matches[0], None
        if len(session_matches) > 1:
            return duplicate_result(session_matches, "duplicate-session-identity")
        if len(url_matches) == 1:
            return url_matches[0], None
        if len(url_matches) > 1:
            return duplicate_result(url_matches, "duplicate-url-identity")
    elif wanted_session:
        if len(session_matches) == 1:
            return session_matches[0], None
        if len(session_matches) > 1:
            return duplicate_result(session_matches, "duplicate-session-identity")
    elif wanted_url:
        if len(url_matches) == 1:
            return url_matches[0], None
        if len(url_matches) > 1:
            return duplicate_result(url_matches, "duplicate-url-identity")
    return None, ConversationFocusResult(ConversationFocusOutcome.NOT_FOUND, "conversation-tab-not-found")


def _select_capture_checkpoint_target(
    pages: Iterable[Mapping[str, object]], locator: ConversationFocusLocator
) -> Mapping[str, object] | None:
    """Find only the persisted first-turn target, before any page actions."""
    if (
        not isinstance(locator, ConversationCaptureLocator)
        or locator.chat_url
        or locator.provider_session_id
        or not locator.provider_target_id
        or locator.send_intent_ever is not True
        or locator.submission_stage != "send-click-acknowledged"
        or not isinstance(locator.prompt_text_digest, str)
        or len(locator.prompt_text_digest) != 64
        or type(locator.baseline_user_count) is not int
        or locator.baseline_user_count != 0
        or type(locator.baseline_assistant_count) is not int
        or locator.baseline_assistant_count != 0
    ):
        return None
    project = parse_project_id(locator.project_url or "")
    if not project:
        return None
    matches = [
        page for page in pages
        if page.get("targetId") == locator.provider_target_id
        and canonical_chat_url(str(page.get("url") or ""))
        and parse_project_id(str(page.get("url") or "")) == project
    ]
    return matches[0] if len(matches) == 1 else None


def _capture_checkpoint_matches(
    snapshot: ChatSnapshot, locator: ConversationCaptureLocator
) -> bool:
    """Prove the sole submitted user turn and its ordered assistant response."""
    user = snapshot.latest_user_ref()
    assistant = next(
        (ref for ref in reversed(snapshot.message_refs) if ref.role == "assistant"),
        None,
    )
    return bool(
        canonical_chat_url(snapshot.url)
        and parse_project_id(snapshot.url) == parse_project_id(locator.project_url or "")
        and snapshot.user_count == 1
        and len(snapshot.user_prompt_refs()) == 1
        and snapshot.assistant_count > 0
        and user is not None
        and assistant is not None
        and user.message_id == snapshot.latest_user_id
        and user.message_id
        and not user.message_id.startswith(("fallback-", "virtualized-prompt-for-"))
        and assistant.message_id == snapshot.latest_assistant_id
        and assistant.message_id
        and not assistant.message_id.startswith("fallback-")
        and user.sequence < assistant.sequence
        and locator.prompt_text_digest
        == PromptFingerprint.from_text(snapshot.latest_user_correlation_text() or "").digest
    )


async def focus_existing_conversation(
    project_root: Path,
    *,
    provider_id: str,
    locator: ConversationFocusLocator,
) -> ConversationFocusResult:
    """Focus a retained GPT tab, opening its durable URL when absent."""
    document = load_provider_config(project_root)
    provider_cfg = (document.get("providers") or {}).get(provider_id)
    if not isinstance(provider_cfg, dict) and provider_id.startswith("gpt-auto-"):
        provider_cfg = (document.get("providers") or {}).get("gpt-auto")
    if not isinstance(provider_cfg, dict):
        return ConversationFocusResult(ConversationFocusOutcome.UNAVAILABLE, "provider-config-unavailable")
    runtime = get_runtime(project_root, GptAutoConfig.from_project_dict(provider_cfg))
    if not await runtime.connect_existing():
        return ConversationFocusResult(ConversationFocusOutcome.UNAVAILABLE, "cdp-unavailable")
    if locator.gateway_session_id:
        focus_live = getattr(runtime, "focus_live_session", None)
        if focus_live is not None:
            reason = await focus_live(locator.gateway_session_id)
            if reason == "focused":
                return ConversationFocusResult(ConversationFocusOutcome.FOCUSED)
    pages = await runtime.bridge.call("list_pages")
    runtime.adopt_existing_dedicated_window(pages)
    scoped = [p for p in pages if runtime.page_belongs_to_dedicated_window(p)]
    selected, result = select_focus_page(scoped, locator)
    # A retained conversation may have been moved to another browser window
    # since admission.  The request-owned URL/session identity is stronger
    # than the gateway's preferred-window hint, so retry the exact selection
    # across all CDP pages when the scoped window has no match.  Ambiguous or
    # conflicting identities remain fail-closed.
    if (
        selected is None
        and result is not None
        and result.outcome is ConversationFocusOutcome.NOT_FOUND
        and scoped != pages
    ):
        selected, result = select_focus_page(pages, locator)
    if result is not None:
        # The dashboard exposes one action rather than separate open/focus
        # controls.  If the exact retained conversation is not currently
        # mounted, open that request-owned URL in the managed GPT window and
        # focus the new page.  Identity conflicts and ambiguity remain
        # fail-closed; only a genuine not-found result can use this fallback.
        chat_url = canonical_chat_url(locator.chat_url or "")
        if result.outcome is not ConversationFocusOutcome.NOT_FOUND or chat_url is None:
            return result
        handle = ""
        try:
            handle = await runtime.create_chat_page()
            await runtime.bridge.call("navigate", {"pageHandle": handle, "url": chat_url})
            await runtime.bridge.call("activate_target", {"pageHandle": handle, "operator": True, "operator_reason": "dashboard-focus"})
            await runtime.bridge.call("keep_page_active", {"pageHandle": handle, "operator": True})
            return ConversationFocusResult(
                ConversationFocusOutcome.FOCUSED,
                "conversation-tab-opened",
            )
        except Exception:
            if handle:
                try:
                    await runtime.bridge.call("close_page", {"pageHandle": handle, "operator": True})
                except Exception:
                    pass
            return ConversationFocusResult(
                ConversationFocusOutcome.UNAVAILABLE,
                "conversation-tab-open-failed",
            )
    if selected is None:
        return ConversationFocusResult(ConversationFocusOutcome.NOT_FOUND, "conversation-tab-not-found")
    handle = str(selected.get("pageHandle") or "")
    if not handle:
        return ConversationFocusResult(ConversationFocusOutcome.UNAVAILABLE, "target-handle-missing")
    # Page.bringToFront/window.focus keeps the renderer visible but does not
    # reliably select the tab in a multi-target browser. Explicitly activate
    # the DevTools target first, then retain the renderer-level focus call.
    await runtime.bridge.call("activate_target", {"pageHandle": handle, "operator": True, "operator_reason": "dashboard-focus"})
    await runtime.bridge.call("keep_page_active", {"pageHandle": handle, "operator": True})
    return ConversationFocusResult(ConversationFocusOutcome.FOCUSED)


async def capture_latest_response(
    project_root: Path,
    *,
    provider_id: str,
    locator: ConversationFocusLocator,
    passive: bool = False,
) -> dict[str, object]:
    """Read a proven terminal response from one exact GPT conversation.

    Missing retained tabs may be reopened at the durable conversation URL for
    an explicit operator action.  ``passive`` is used by the watchdog and is
    strictly existing-target-only: it never creates, navigates, activates,
    refreshes, or materializes a page.
    """
    document = load_provider_config(project_root)
    provider_cfg = (document.get("providers") or {}).get(provider_id)
    if not isinstance(provider_cfg, dict) and provider_id.startswith("gpt-auto-"):
        provider_cfg = (document.get("providers") or {}).get("gpt-auto")
    if not isinstance(provider_cfg, dict):
        return {"outcome": "unavailable", "reason": "provider-config-unavailable"}
    runtime = get_runtime(project_root, GptAutoConfig.from_project_dict(provider_cfg))
    if not await runtime.connect_existing():
        return {"outcome": "unavailable", "reason": "cdp-unavailable"}
    pages = await runtime.bridge.call("list_pages")
    runtime.adopt_existing_dedicated_window(pages)
    scoped = [p for p in pages if runtime.page_belongs_to_dedicated_window(p)]
    selected, result = select_focus_page(scoped, locator)
    checkpoint_locator = None
    if (
        selected is None
        and result is not None
        and result.outcome is ConversationFocusOutcome.NOT_FOUND
        and scoped != pages
    ):
        selected, result = select_focus_page(pages, locator)
    if (
        selected is None
        and result is not None
        and result.outcome is ConversationFocusOutcome.NOT_FOUND
    ):
        checkpoint_page = _select_capture_checkpoint_target(pages, locator)
        if checkpoint_page is not None:
            selected, result = checkpoint_page, None
            checkpoint_locator = locator
    if (
        selected is None
        and result is not None
        and result.outcome is ConversationFocusOutcome.NOT_FOUND
    ):
        chat_url = canonical_chat_url(locator.chat_url or "")
        if chat_url is not None and not passive:
            try:
                reopen = getattr(runtime, "reopen_conversation_page", None)
                if callable(reopen):
                    selected = await reopen(chat_url)
                else:
                    handle = await runtime.create_chat_page()
                    await runtime.bridge.call(
                        "navigate", {"pageHandle": handle, "url": chat_url}
                    )
                    selected = {"pageHandle": handle, "url": chat_url, "type": "page"}
                result = None
            except Exception:
                return {
                    "outcome": "unavailable",
                    "reason": "conversation-tab-open-failed",
                }
    if selected is None:
        return {
            "outcome": "unavailable",
            "reason": result.reason if result else "conversation-tab-not-found",
        }
    duplicates = [p for p in pages if canonical_chat_url(str(p.get("url") or ""))
                  == canonical_chat_url(str(selected.get("url") or ""))]
    if len(duplicates) > 1:
        if not isinstance(locator, ConversationCaptureLocator) or not locator.prompt_text_digest:
            return {"outcome": "unavailable", "reason": "duplicate-turn-proof-missing"}
        proven = []
        for candidate in duplicates:
            try:
                candidate_page = await runtime.gpt_browser.page_by_handle(str(candidate["pageHandle"]))
                candidate_snapshot = ChatSnapshot.from_bridge(await runtime.gpt_browser.snapshot(
                    candidate_page, signals=runtime.config.workflow.bridge_signals(),
                ))
                user = candidate_snapshot.latest_user_ref()
                assistant = next((ref for ref in reversed(candidate_snapshot.message_refs) if ref.role == "assistant"), None)
                if (
                    canonical_chat_url(candidate_snapshot.url) == canonical_chat_url(str(selected.get("url") or ""))
                    and not candidate_snapshot.generating and not candidate_snapshot.error_present
                    and candidate_snapshot.latest_assistant_id
                    and candidate_snapshot.terminal_witness_assistant_id == candidate_snapshot.latest_assistant_id
                    and candidate_snapshot.dom_signals.intersection({"completion-control", "response-complete-status"})
                    and user is not None and assistant is not None and user.sequence < assistant.sequence
                    and PromptFingerprint.from_text(candidate_snapshot.latest_user_correlation_text() or "").digest == locator.prompt_text_digest
                    and (locator.baseline_user_count is None or candidate_snapshot.user_count == locator.baseline_user_count + 1)
                ):
                    proven.append(candidate)
            except Exception:
                continue
        if not proven:
            return {"outcome": "unavailable", "reason": "duplicate-owned-terminal-not-proven"}
        selected = min(proven, key=lambda p: str(p.get("targetId") or p.get("pageHandle") or ""))
    handle = str(selected.get("pageHandle") or "")
    if not handle:
        return {"outcome": "unavailable", "reason": "target-handle-missing"}
    # Provider capture is used by watchdog recovery as well as the dashboard
    # button. It must remain observation-only: foregrounding here makes a
    # quiet/stale recovery loop steal focus and cycle through GPT tabs. Only
    # an explicit focus/open-tab action may activate a target.
    if not passive and checkpoint_locator is None:
        await runtime.bridge.call("keep_page_active", {"pageHandle": handle, "operator": True})
    page = await runtime.gpt_browser.page_by_handle(handle)
    if not passive and checkpoint_locator is None:
        await runtime.gpt_browser.materialize_latest_assistant_turn(page)
    snapshot = ChatSnapshot.from_bridge(
        await runtime.gpt_browser.snapshot(
            page,
            signals=runtime.config.workflow.bridge_signals(),
        )
    )
    if checkpoint_locator is not None:
        try:
            current_page = await runtime.gpt_browser.page_by_handle(handle)
        except Exception:
            return {"outcome": "unavailable", "reason": "provider-target-no-longer-available"}
        if (
            current_page.target_id != checkpoint_locator.provider_target_id
            or canonical_chat_url(current_page.url) != canonical_chat_url(snapshot.url)
        ):
            return {"outcome": "unavailable", "reason": "provider-target-checkpoint-mismatch"}
    if checkpoint_locator is not None and (
        getattr(page, "target_id", None) != checkpoint_locator.provider_target_id
        or canonical_chat_url(snapshot.url) != canonical_chat_url(str(selected.get("url") or ""))
        or not _capture_checkpoint_matches(snapshot, checkpoint_locator)
    ):
        return {"outcome": "unavailable", "reason": "provider-target-checkpoint-mismatch"}
    expected_chat_url = canonical_chat_url(locator.chat_url or "")
    if expected_chat_url and canonical_chat_url(snapshot.url) != expected_chat_url:
        return {
            "outcome": "unavailable",
            "reason": "conversation-identity-mismatch",
        }
    failure_signals = {
        "auth-required",
        "conversation-load-failed",
        "error-page",
    }
    if snapshot.error_present or snapshot.dom_signals.intersection(failure_signals):
        return {"outcome": "unavailable", "reason": "provider-error-page"}
    if (
        snapshot.generating
        or not snapshot.latest_assistant_text
        or not snapshot.latest_assistant_text.strip()
        or not snapshot.latest_assistant_id
        or snapshot.terminal_witness_assistant_id != snapshot.latest_assistant_id
        or not snapshot.dom_signals.intersection(
            {"completion-control", "response-complete-status"}
        )
    ):
        return {
            "outcome": "unavailable",
            "reason": "terminal-response-not-proven",
        }
    return {
        "outcome": "captured",
        "snapshot": snapshot,
        "binding": {
            "chat-url": canonical_chat_url(snapshot.url),
            "provider-session-id": parse_provider_session_id(snapshot.url),
            "target-id": str(getattr(page, "target_id", "") or "") or None,
        },
    }

__all__ = ["capture_latest_response", "focus_existing_conversation", "select_focus_page"]
