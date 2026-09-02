"""Strict existing-conversation discovery for the GPT-auto provider."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from audiagentic.components.providers.contracts.conversation_focus import (
    ConversationFocusLocator,
    ConversationFocusOutcome,
    ConversationFocusResult,
)
from audiagentic.components.providers.services.config.provider_config import (
    load_provider_config,
)

from .config import GptAutoConfig
from .runtime_registry import get_runtime
from .urls import parse_project_id, parse_provider_session_id


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

    if wanted_url and wanted_session:
        intersection = [p for p in url_matches if p in session_matches]
        if len(intersection) == 1:
            return intersection[0], None
        if len(intersection) > 1:
            return None, ConversationFocusResult(ConversationFocusOutcome.AMBIGUOUS, "duplicate-target-identity")
        if url_matches and session_matches:
            return None, ConversationFocusResult(ConversationFocusOutcome.IDENTITY_CONFLICT, "url-session-mismatch")
        if len(session_matches) == 1:
            return session_matches[0], None
        if len(session_matches) > 1:
            return None, ConversationFocusResult(ConversationFocusOutcome.AMBIGUOUS, "duplicate-session-identity")
        if len(url_matches) == 1:
            return url_matches[0], None
        if len(url_matches) > 1:
            return None, ConversationFocusResult(ConversationFocusOutcome.AMBIGUOUS, "duplicate-url-identity")
    elif wanted_session:
        if len(session_matches) == 1:
            return session_matches[0], None
        if len(session_matches) > 1:
            return None, ConversationFocusResult(ConversationFocusOutcome.AMBIGUOUS, "duplicate-session-identity")
    elif wanted_url:
        if len(url_matches) == 1:
            return url_matches[0], None
        if len(url_matches) > 1:
            return None, ConversationFocusResult(ConversationFocusOutcome.AMBIGUOUS, "duplicate-url-identity")
    return None, ConversationFocusResult(ConversationFocusOutcome.NOT_FOUND, "conversation-tab-not-found")


async def focus_existing_conversation(
    project_root: Path,
    *,
    provider_id: str,
    locator: ConversationFocusLocator,
) -> ConversationFocusResult:
    """Rediscover and activate one existing GPT tab without creating/navigating."""
    document = load_provider_config(project_root)
    provider_cfg = (document.get("providers") or {}).get(provider_id)
    if not isinstance(provider_cfg, dict) and provider_id.startswith("gpt-auto-"):
        provider_cfg = (document.get("providers") or {}).get("gpt-auto")
    if not isinstance(provider_cfg, dict):
        return ConversationFocusResult(ConversationFocusOutcome.UNAVAILABLE, "provider-config-unavailable")
    runtime = get_runtime(project_root, GptAutoConfig.from_project_dict(provider_cfg))
    if not await runtime.connect_existing():
        return ConversationFocusResult(ConversationFocusOutcome.UNAVAILABLE, "cdp-unavailable")
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
        return result
    if selected is None:
        return ConversationFocusResult(ConversationFocusOutcome.NOT_FOUND, "conversation-tab-not-found")
    handle = str(selected.get("pageHandle") or "")
    if not handle:
        return ConversationFocusResult(ConversationFocusOutcome.UNAVAILABLE, "target-handle-missing")
    # Page.bringToFront/window.focus keeps the renderer visible but does not
    # reliably select the tab in a multi-target browser. Explicitly activate
    # the DevTools target first, then retain the renderer-level focus call.
    await runtime.bridge.call("activate_target", {"pageHandle": handle})
    await runtime.bridge.call("keep_page_active", {"pageHandle": handle})
    return ConversationFocusResult(ConversationFocusOutcome.FOCUSED)


__all__ = ["focus_existing_conversation", "select_focus_page"]
