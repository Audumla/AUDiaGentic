"""A2A facade settings: the ``a2a`` section of the resolved settings (SH65b-3).

Imports no SDK, so the doctor can validate and report on the section when the optional ``a2a`` extra is missing.
Machine scopes only (user, explicit): a project's own settings never change what the machine serves. Nothing
here reads an environment variable or opens a socket.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from audiagentic.foundation.contracts.errors import make_error_factory

error = make_error_factory("VAL", "A2A", "agents")

_PROJECT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_LOOPBACK = re.compile(r"http://127\.0\.0\.1:([0-9]{1,5})")
LOOPBACK_HOST = "127.0.0.1"


@dataclass(frozen=True)
class A2aSettings:
    enabled: bool
    port: int | None
    base_url: str | None
    projects: tuple[str, ...]


def parse_settings(section: Mapping[str, Any] | None) -> A2aSettings:
    """Validate the ``a2a`` settings section; refuse anything that would expose the facade unsafely."""
    section = dict(section or {})
    enabled = section.get("enabled", False)
    port = section.get("port")
    projects = tuple(section.get("projects") or ())
    base_url = section.get("base_url")
    if not isinstance(enabled, bool):
        raise error(1, "a2a.enabled must be true or false")
    if any(not isinstance(item, str) or not _PROJECT_ID.fullmatch(item) for item in projects):
        raise error(2, "a2a.projects must be gateway project ids (lowercase letters, digits, - and _)")
    if enabled and (not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535):
        raise error(3, "a2a.port is required and must be 1-65535 when the facade is enabled")
    if enabled and not projects:
        raise error(4, "a2a.projects must name at least one project when the facade is enabled")
    if base_url is None and enabled:
        base_url = f"http://{LOOPBACK_HOST}:{port}"
    if base_url is not None:
        base_url = _validated_origin(base_url)
    return A2aSettings(enabled=enabled, port=port if isinstance(port, int) else None, base_url=base_url, projects=projects)


def _validated_origin(value: Any) -> str:
    """An HTTPS origin (what a TLS proxy publishes) or the loopback http origin; never a path, credentials or plain http elsewhere."""
    if not isinstance(value, str) or not value or value != value.strip() or any(c.isspace() for c in value):
        raise error(5, "a2a.base_url must be a non-empty origin")
    if _LOOPBACK.fullmatch(value):
        return value
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.password is not None
            or parts.path or parts.query or parts.fragment or value.endswith("/") or value.endswith(":")):
        raise error(5, "a2a.base_url must be an https origin (no path or credentials) or http://127.0.0.1:PORT")
    return value


def load_settings() -> A2aSettings:
    from audiagentic.foundation.config.settings import resolve_settings_cached

    return parse_settings(resolve_settings_cached(machine_only=True).get("a2a"))
