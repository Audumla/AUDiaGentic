"""Gateway-dashboard URL for GPT-auto's dedicated-window anchor."""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_ANCHOR_QUERY_KEY = "audiagentic-window-anchor"


def gateway_dashboard_url() -> str:
    """Resolve the gateway-owned dashboard without importing gateway internals."""
    explicit = os.environ.get("AUDIAGENTIC_GATEWAY_DASHBOARD_URL")
    if explicit:
        return explicit.rstrip("/")
    port = os.environ.get("AUDIAGENTIC_GATEWAY_PORT", "8765")
    path = os.environ.get("AUDIAGENTIC_GATEWAY_DASHBOARD_PATH", "/dashboard")
    return f"http://127.0.0.1:{port}/{path.lstrip('/')}"


def gateway_dashboard_anchor_url() -> str:
    """Return the dashboard URL used to durably mark a managed window.

    CDP window ids and target ids are scoped to one browser connection, so
    they cannot identify a window after a gateway restart. The dashboard tab
    is the durable, user-visible anchor. A small query marker lets us prefer
    a tab created by this runtime when several dashboard tabs exist.
    """
    parts = urlsplit(gateway_dashboard_url())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[_ANCHOR_QUERY_KEY] = "1"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def is_gateway_dashboard_url(value: str) -> bool:
    """Match the gateway dashboard while ignoring harmless URL decoration."""
    if not isinstance(value, str) or not value:
        return False
    expected = urlsplit(gateway_dashboard_url())
    observed = urlsplit(value)
    expected_path = expected.path.rstrip("/") or "/"
    observed_path = observed.path.rstrip("/") or "/"
    return (
        observed.scheme.lower() == expected.scheme.lower()
        and observed.netloc.lower() == expected.netloc.lower()
        and observed_path == expected_path
    )


def is_gateway_dashboard_anchor_url(value: str) -> bool:
    """Return whether a dashboard tab carries this runtime's anchor marker."""
    if not is_gateway_dashboard_url(value):
        return False
    query = dict(parse_qsl(urlsplit(value).query, keep_blank_values=True))
    return query.get(_ANCHOR_QUERY_KEY) == "1"


__all__ = [
    "gateway_dashboard_anchor_url",
    "gateway_dashboard_url",
    "is_gateway_dashboard_anchor_url",
    "is_gateway_dashboard_url",
]
