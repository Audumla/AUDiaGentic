"""Pure ChatGPT project and conversation URL helpers."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

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
    return parse_provider_session_id(url) == provider_session_id
