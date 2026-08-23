"""Pure ChatGPT project and conversation URL helpers."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from .window_anchor import is_gateway_dashboard_url

_PROJECT_RE = re.compile(r"/g/(g-p-[^/]+)")
_CHAT_RE = re.compile(r"/c/([^/?#]+)")


def parse_project_id(url: str) -> str | None:
    match = _PROJECT_RE.search(urlsplit(url).path)
    return match.group(1) if match else None


def parse_provider_session_id(url: str) -> str | None:
    match = _CHAT_RE.search(urlsplit(url).path)
    return match.group(1) if match else None


def canonical_project_url(url: str) -> str:
    parts = urlsplit(url)
    project = parse_project_id(url)
    if not project:
        raise ValueError("URL does not identify a ChatGPT project")
    host = "chatgpt.com" if parts.hostname in {"chatgpt.com", "chat.openai.com"} else parts.netloc
    return urlunsplit(("https", host, f"/g/{project}", "", ""))


def canonical_chat_url(url: str) -> str | None:
    project = parse_project_id(url)
    session_id = parse_provider_session_id(url)
    if not project or not session_id:
        return None
    return f"https://chatgpt.com/g/{project}/c/{session_id}"


def url_matches_provider_session(url: str, provider_session_id: str) -> bool:
    """Match only a conversation that remains inside a ChatGPT Project.

    A bare ``/c/<id>`` URL is a normal ChatGPT conversation, not an owned
    gpt-auto target.  Treating it as one would let a persisted bad URL reopen
    a session outside its configured project.
    """
    return bool(parse_project_id(url)) and parse_provider_session_id(url) == provider_session_id


def is_gpt_auto_relevant_url(url: str) -> bool:
    """True for URLs a gpt-auto-owned tab can plausibly have.

    GP42: PythonCdpBridge._refresh_pages() used to resolve windowId for
    EVERY page target on the whole shared browser, including completely
    unrelated tabs (other websites, other tools) -- one extra
    Browser.getWindowForTarget CDP round-trip per tab, on every call. A
    machine with dozens of ordinary browsing tabs open turns one
    list_pages() call into dozens of round-trips. Used to scope that
    lookup to tabs that could actually be ours: a real ChatGPT
    conversation/project, the gateway's HTTP dashboard, or a freshly
    created but not-yet-navigated about:blank tab.
    """
    if url in ("", "about:blank"):
        return True
    if url.startswith("data:"):
        return True
    if is_gateway_dashboard_url(url):
        return True
    hostname = urlsplit(url).hostname
    return hostname in {"chatgpt.com", "chat.openai.com"}
