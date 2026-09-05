"""Loopback-only, gateway-owned operator dashboard.

The dashboard is deliberately independent of provider/browser adapters.  It
reads only gateway-owned durable records and the existing read-only live
session/queue snapshots; prompts, outputs, provider-private references and
request metadata are never included in its public payload.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from audiagentic.components.agents.gateway.mapping import normalize_chat_title

DEFAULT_RECENT_WINDOW_SECONDS = 12 * 60 * 60
MAX_RECENT_WINDOW_SECONDS = 30 * 24 * 60 * 60
RECENT_WINDOW_ENV = "AUDIAGENTIC_GATEWAY_DASHBOARD_RECENT_SECONDS"
_ACTIVE_REQUEST_STATES = frozenset({"queued", "dispatching", "running"})
_ACTIVE_SESSION_STATES = frozenset({"active", "closing"})
_FAILED_REQUEST_STATES = frozenset(
    {"failed", "rejected", "interrupted", "timed-out", "expired", "abandoned"}
)


def recent_window_seconds(value: object | None = None) -> int:
    """Return a bounded dashboard window, using the gateway env by default."""
    raw = os.environ.get(RECENT_WINDOW_ENV) if value is None else value
    try:
        parsed = int(raw) if not isinstance(raw, bool) else 0
    except (TypeError, ValueError):
        parsed = 0
    if parsed < 1 or parsed > MAX_RECENT_WINDOW_SECONDS:
        return DEFAULT_RECENT_WINDOW_SECONDS
    return parsed


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_visible_in_window(row: dict[str, Any], cutoff: datetime) -> bool:
    """Keep active work visible even if it has been idle longer than the window."""
    if row.get("live") or row.get("state") in _ACTIVE_REQUEST_STATES | _ACTIVE_SESSION_STATES:
        return True
    timestamp = _parse_timestamp(_most_recent(row))
    return timestamp is not None and timestamp >= cutoff


def _valid_override(value: object | None) -> int | None:
    """Return a valid dashboard override, or None to use gateway configuration."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 1 or parsed > MAX_RECENT_WINDOW_SECONDS:
        return None
    return parsed


def dashboard_snapshot(
    service_root: Path,
    *,
    recent_seconds: int | None = None,
    configured_recent_seconds: int | None = None,
) -> dict[str, Any]:
    """Return the complete redacted cross-project gateway operator snapshot."""
    from audiagentic.components.agents.gateway import api
    from audiagentic.components.agents.gateway.service.known_projects import load_known_projects
    from audiagentic.components.agents.gateway.service.dashboard_images import project_image_id, image_path
    from audiagentic.components.agents.gateway.session.sessions import peek_session_runtime

    registry = load_known_projects(service_root / "known-projects.json")
    runtime = peek_session_runtime()
    live = runtime.session_snapshot_all() if runtime is not None else {}
    projects: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    effective_window = _valid_override(recent_seconds)
    if effective_window is None:
        effective_window = recent_window_seconds(configured_recent_seconds)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=effective_window)
    window_source = "dashboard" if _valid_override(recent_seconds) is not None else "gateway"

    for known in registry.projects:
        root = known.project_root
        if not root.exists():
            continue
        # The MCP list operation is deliberately the compact V4 task-status
        # projection.  The dashboard has its own bounded operator projection
        # so request identity, lifecycle, and live activity evidence remain
        # visible without reopening the public status contract.
        records = api.list_dashboard_requests(root)
        sessions = api.list_execution_sessions(root)
        all_session_rows = sorted(
            (_session_row(session, live.get(session["session-id"])) for session in sessions),
            key=_session_sort_key,
        )
        # Keep active/non-terminal sessions ahead of closed history.  The
        # durable session id is the only secondary key: timestamps change as
        # work progresses and would make the dashboard jump between polls.
        # Session-backed requests inherit their immutable execution identity
        # from the session header.  Keep the request's durable snapshot
        # untouched, but omit the repeated profile/provider/model fields from
        # the dashboard projection.  One-shot requests still carry their own
        # execution identity because there is no session header to inherit.
        all_request_rows = sorted(
            (
                _request_row(record, include_execution=not bool(record.get("session-id")))
                for record in records
            ),
            key=_request_sort_key,
        )
        request_rows = [row for row in all_request_rows if _is_visible_in_window(row, cutoff)]
        recent_request_ids = {row.get("session-id") for row in request_rows}
        session_rows = [
            row for row in all_session_rows
            if _is_visible_in_window(row, cutoff) or row.get("session-id") in recent_request_ids
        ]
        requests.extend({**row, "project": root.name} for row in request_rows)
        failures.extend(
            {**row, "project": root.name}
            for row in request_rows
            if row["state"] in _FAILED_REQUEST_STATES
        )
        projects.append(
            {
                "name": root.name,
                "project-id": project_image_id(root),
                "image-version": str(image_path(service_root, project_image_id(root)).stat().st_mtime_ns) if image_path(service_root, project_image_id(root)).is_file() else "",
                "config-status": known.config_status,
                "last-seen-at": known.last_seen_at.isoformat(),
                "queues": api.get_queue_manager().project_queue_depths(root),
                "sessions": session_rows,
                "requests": request_rows,
            }
        )

    projects.sort(key=lambda project: project["name"].casefold())
    requests.sort(key=_request_sort_key)
    failures.sort(key=_request_sort_key)
    counts = Counter(row["state"] for row in requests)
    return {
        "contract-version": "v1",
        "dashboard": {
            "recent-window-seconds": effective_window,
            "recent-window-source": window_source,
            "active-work-always-visible": True,
            "maximum-recent-window-seconds": MAX_RECENT_WINDOW_SECONDS,
        },
        "runtime": api._runtime_fingerprint(),
        "projects": projects,
        "requests": requests,
        "failures": failures,
        "counts": dict(sorted(counts.items())),
        "provider-diagnostics": _provider_diagnostics(),
    }


def _request_row(
    status: dict[str, Any],
    *,
    include_execution: bool = True,
) -> dict[str, Any]:
    """Select bounded request facts suitable for an unauthenticated loopback page."""
    from audiagentic.components.agents.status.task_status_v4 import project_activity_type

    visible = (
        "request-id",
        "state", "session-id", "provider-turn-pending", "created-at", "updated-at",
        "started-at", "finished-at", "last-activity-at", "watchdog-state", "watchdog-reason",
        "activity", "activity-sequence", "activity-source", "activity-lease-expires-at",
        "latest-transition", "error", "provider-chat-url", "provider-chat-title",
        "diagnostics",
        "output-preview", "output-truncated", "response-artifact",
    )
    if include_execution:
        visible = (
            "request-id", "execution-profile-id", "resolved-provider-id", "resolved-model-id",
            *visible[1:],
        )
    # Keep provider identity available for navigation eligibility even when
    # execution fields are intentionally omitted from a session-backed row.
    provider_id = str(
        status.get("resolved-provider-id")
        or status.get("provider-id")
        or ""
    )
    row = {key: status.get(key) for key in visible if status.get(key) is not None}
    # ``provider-turn-pending`` is useful while a request is active, but a
    # terminal request must not look live merely because cancellation retained
    # historical side-effect evidence for recovery/audit.  The terminal
    # diagnostic remains available separately.
    if row.get("state") not in _ACTIVE_REQUEST_STATES:
        row.pop("provider-turn-pending", None)
    activity_type = project_activity_type(status)
    if activity_type is not None:
        row["activity-type"] = activity_type
    # A live GPT request can be focused before ChatGPT has published the
    # conversation URL.  The gateway-session identity is enough for the
    # provider's in-process live-page fallback; do not make the dashboard
    # wait for URL discovery before exposing the action.
    row["focus-tab-available"] = bool(row.get("provider-chat-url")) or (
        provider_id.startswith("gpt-auto")
        and str(row.get("state") or "") in {"dispatching", "running", "active"}
    )
    return row


def _session_row(record: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any]:
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    row = {
        "session-id": record["session-id"],
        "execution-profile-id": record.get("execution-profile-id"),
        "provider-id": session_store.session_provider_id(record),
        "model-id": session_store.session_model_id(record),
        "state": record.get("state"),
        "runtime-state": record.get("runtime-state"),
        "live": record.get("live", False),
        "created-at": session_store.session_created_at(record),
        "updated-at": session_store.session_updated_at(record),
        "last-activity-at": session_store.session_last_activity_at(record),
        "closed-at": session_store.session_closed_at(record),
        "close-reason": record.get("close-reason"),
        "turn-count": session_store.session_turn_count(record),
    }
    provider_metadata = session_store.session_provider_metadata(record)
    chat_title = normalize_chat_title(provider_metadata.get("chat-title"))
    if chat_title is not None:
        row["provider-chat-title"] = chat_title
    if live:
        row.update({
            "pending-turns": live.get("pending-turns", 0),
            "turn-active": live.get("turn-active", False),
            "current-request-id": live.get("current-request-id"),
        })
    return {key: value for key, value in row.items() if value is not None}


def _most_recent(row: dict[str, Any]) -> str:
    """Return the newest valid durable timestamp, regardless of field order."""
    candidates = (
        value
        for key in ("updated-at", "last-activity-at", "closed-at", "created-at")
        if (value := row.get(key))
    )
    parsed = [(stamp, _parse_timestamp(stamp)) for stamp in candidates]
    valid = [(stamp, moment) for stamp, moment in parsed if moment is not None]
    if not valid:
        return ""
    return max(valid, key=lambda item: item[1])[0]


def _session_is_terminal(row: dict[str, Any]) -> bool:
    """Return whether a session is closed, expired, or failed."""
    from audiagentic.components.agents.gateway.session import sessions_store

    return row.get("state") in sessions_store.SESSION_TERMINAL_STATES


def _session_sort_key(row: dict[str, Any]) -> tuple[bool, str]:
    """Sort sessions by lifecycle first, then stable session identity."""
    return (_session_is_terminal(row), str(row.get("session-id") or "").casefold())


def _request_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    """Sort requests by owning session id, then request id."""
    return (
        str(row.get("session-id") or "").casefold(),
        str(row.get("request-id") or "").casefold(),
    )


def _provider_diagnostics() -> dict[str, Any]:
    from audiagentic.components.providers.providers_api import (
        get_provider_load_errors,
        list_canonical_provider_ids,
    )

    errors = get_provider_load_errors()
    return {
        "providers-loaded": len(list_canonical_provider_ids()),
        "provider-load-errors": [
            {"file": file_name, "message": message}
            for file_name, message in errors
        ],
    }


def render_dashboard_html(
    snapshot_path: str,
    *,
    focus_path: str = "/dashboard/focus",
    purge_session_path: str = "/dashboard/purge-session",
    focus_token: str = "",
) -> bytes:
    """Return a self-refreshing page.  It has no provider/browser dependency."""
    source = json.dumps(snapshot_path)
    focus_source = json.dumps(focus_path)
    purge_source = json.dumps(purge_session_path)
    token_source = json.dumps(focus_token)
    html = """<!doctype html>
<meta charset="utf-8"><title>Agent gateway dashboard</title>
<style>
:root { color-scheme: dark; --bg:#0b1020; --panel:#131b31; --panel2:#182441; --line:#293858; --muted:#91a0bd; --text:#e8eefb; --teal:#45d6d6; --green:#5ee39a; --amber:#f7c873; --red:#ff7885; --purple:#b39bff; --shadow:0 18px 45px #05091480; }
* { box-sizing:border-box } body { background:radial-gradient(circle at 85% 0,#1c3860 0,var(--bg) 42%); color:var(--text); font:14px/1.45 system-ui,sans-serif; margin:0; padding:20px; }
main { max-width:1500px; margin:auto } h1,h2,h3 { margin:0 } h1 { font-size:28px; font-weight:750; letter-spacing:-.02em } h2 { font-size:17px; margin:24px 0 10px } h3 { font-size:14px } .muted { color:var(--muted) } .eyebrow { color:var(--teal); font-size:11px; font-weight:700; letter-spacing:.14em; text-transform:uppercase }
.top,.toolbar,.session-head,.project-head { display:flex; gap:12px; align-items:center; justify-content:space-between; flex-wrap:wrap } .toolbar { background:#0e1930cc; border:1px solid var(--line); border-radius:12px; padding:8px 10px; margin:12px 0 }
.pulse { display:flex; gap:8px; align-items:center; color:var(--green); font-weight:650 } .dot { width:9px; height:9px; border-radius:50%; background:var(--green); box-shadow:0 0 14px var(--green) } .pulse.stale .dot { background:var(--amber); box-shadow:0 0 14px var(--amber) } .pulse.stale { color:var(--amber) }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(128px,1fr)); gap:10px; margin:12px 0 }.card,.project { background:linear-gradient(145deg,var(--panel2),#10182c); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow) }.session,.orphan { background:#10182c; border:1px solid var(--line); border-radius:8px; box-shadow:none }.card { padding:9px 11px }.card .label { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.08em }.value { font-size:22px; font-weight:750; margin-top:3px }.value.good { color:var(--green) }.value.warn { color:var(--amber) }.value.bad { color:var(--red) }.value.info { color:var(--teal) }
.project { padding:14px; margin:14px 0; container-type:inline-size; --content-inset:10px; --request-cols:minmax(0,1.7fr) minmax(82px,.7fr) minmax(0,1.25fr) minmax(112px,.9fr) 52px }.project-head { margin-bottom:8px }.project-name { display:flex; align-items:center; gap:8px; font-weight:750; font-size:15px }.project-name .icn { color:var(--purple); width:16px; height:16px; display:inline-grid; place-items:center }.pills { display:flex; gap:6px; flex-wrap:wrap }.pill { border-radius:999px; padding:3px 9px; font-size:11px; font-weight:650; border:1px solid var(--line); color:var(--muted) }.pill.state-completed { color:var(--green); border-color:#254a37 }.pill.state-failed,.pill.state-rejected,.pill.state-interrupted,.pill.state-timed-out,.pill.state-expired,.pill.state-abandoned { color:var(--red); border-color:#5a2a30 }.pill.state-queued,.pill.state-running,.pill.state-dispatching,.pill.state-active { color:var(--amber); border-color:#5a4a24 }
#projects.layout-columns { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr)); gap:14px; align-items:start } #projects.layout-columns .project { margin:0; min-width:0 } #projects.layout-rows { display:block } .work-section { margin-top:10px } .work-section-head { display:flex; align-items:center; gap:8px; margin:0 var(--content-inset) 6px; padding:5px 6px; border-bottom:1px solid #3b5278; color:var(--text) } .work-section-active .work-section-head { border-color:#5a4a24 } .work-section-completed .work-section-head { border-color:#254a37 } .work-section-failed .work-section-head { border-color:#5a2a30 } .work-section-head h3 { font-size:12px; letter-spacing:.1em; text-transform:uppercase; font-weight:750 } .section-count { color:var(--muted); border:1px solid var(--line); border-radius:999px; padding:1px 7px; font-size:11px; font-variant-numeric:tabular-nums } .request-grid { display:grid; gap:4px } .request-header,.request-row { display:grid; grid-template-columns:var(--request-cols); gap:8px; align-items:center } .request-header { margin-inline:var(--content-inset); color:var(--muted); font-size:10px; font-weight:650; letter-spacing:.06em; text-transform:uppercase; padding:0 7px 2px } .request-header > div { display:flex; align-items:center; min-width:0; min-height:24px } .request-header > div,.request-row > div { min-width:0; overflow-wrap:anywhere } .request-row { min-height:34px; padding:5px 7px; border:0; border-radius:0; background:transparent } .request-row .request-identity { display:flex; gap:5px; align-items:center; flex-wrap:nowrap; min-width:0 } .request-row .request-id { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap } .request-row .request-title { color:var(--text); font-size:12px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap } .request-row .request-meta { color:var(--muted); font-size:12px; min-width:0 } .request-row .request-updated { white-space:nowrap; font-variant-numeric:tabular-nums } .request-row .request-error { color:var(--red); font-size:12px; min-width:0 } .session-actions { display:flex; gap:5px; align-items:center; justify-content:flex-end; min-width:0 } .icon-button { width:26px; min-width:26px!important; height:26px; flex:0 0 26px; padding:0!important; border:1px solid transparent; background:transparent; display:inline-grid; place-items:center } .icon-button svg { width:15px; height:15px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round } .icon-button:hover,.icon-button.feedback { border-color:var(--teal); background:#0b1529; color:var(--teal) }
.queue { font:12px ui-monospace,monospace; color:var(--muted); margin-top:2px }.sessions { display:grid; gap:6px }.session { overflow:hidden; position:relative; border-left:0 }.session::before { content:""; position:absolute; inset:0 auto 0 0; width:3px; background:var(--line) }.session.state-completed::before { background:var(--green) }.session.state-failed::before,.session.state-rejected::before,.session.state-interrupted::before,.session.state-timed-out::before,.session.state-expired::before,.session.state-abandoned::before { background:var(--red) }.session.state-queued::before,.session.state-running::before,.session.state-dispatching::before,.session.state-active::before { background:var(--amber) }.session summary { cursor:pointer; list-style:none; padding:8px var(--content-inset) }.session summary::-webkit-details-marker { display:none }.session-head { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center }.session-identity { min-width:0 }.session-chat-title { color:var(--text); font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-top:2px }.session-body { border-top:1px solid var(--line); padding:0 var(--content-inset) 8px }
.request-row .request-id { flex:0 1 auto } .request-row .request-title { flex:1 1 auto } .request-row .request-execution { color:var(--muted); font-size:11px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.badge { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 8px; font-size:12px; white-space:nowrap }.activity-badge { display:inline-flex; align-items:center; gap:4px; max-width:100%; min-width:0; border:1px solid #2b5665; border-radius:999px; padding:1px 6px; color:var(--teal); background:#102938; font-size:11px; line-height:1.25; white-space:nowrap }.activity-kind { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }.activity-seq { flex:0 0 auto; color:var(--muted); font-size:11px; font-variant-numeric:tabular-nums }.state-completed { color:var(--green) }.state-failed,.state-rejected,.state-interrupted,.state-timed-out,.state-expired,.state-abandoned { color:var(--red) }.state-queued,.state-running,.state-dispatching,.state-active { color:var(--amber) }.live { color:var(--amber); font-size:12px; font-weight:650 }.session-profile { color:var(--muted); font-size:11px; font-weight:500 } code { color:var(--teal); font:12px ui-monospace,SFMono-Regular,Consolas,monospace }
.flag { display:inline-block; background:#1c2740; border:1px solid var(--line); color:var(--muted); border-radius:6px; padding:1px 7px; font-size:11px; margin-left:5px }.flag.alert { color:var(--red); border-color:#5a2a30; background:#2a1418; font-weight:650 }.flag.warn { color:var(--amber); border-color:#5a4a24; background:#241c10; font-weight:650 }.flag.progress { color:var(--amber); border-color:#5a4a24; background:#241c10 }
.flag.stale { color:var(--muted); border-style:dashed }
.orphan { padding:10px; margin:10px 0 } select,label { color:var(--text) } select { background:#0b1529; border:1px solid var(--line); border-radius:7px; padding:6px }
.empty { color:var(--muted); padding:24px; text-align:center; border:1px dashed var(--line); border-radius:12px }
input[type=number],button,.action-button { background:#0b1529; border:1px solid var(--line); border-radius:7px; color:var(--text); padding:6px 8px } input[type=number] { width:100px } button,.action-button { cursor:pointer } button:hover,.action-button:hover { border-color:var(--teal) } .action-button { box-sizing:border-box; display:inline-flex; align-items:center; justify-content:center; font-family:inherit; font-size:11px; height:28px; min-width:88px; line-height:1.2; white-space:nowrap; text-decoration:none; vertical-align:middle } .chat-link { color:var(--teal) } .chat-link:hover { text-decoration:none } .purge-session { color:var(--red) }
@media (max-width:700px) { body { padding:14px }.session-head { grid-template-columns:1fr }.session-body { overflow-x:auto } }
@container (max-width:560px) { .session-head { grid-template-columns:1fr } .session-actions { justify-content:flex-start } }
@container (max-width:440px) { .request-header,.request-row { grid-template-columns:minmax(0,1.45fr) minmax(78px,.75fr) minmax(0,1fr) 108px 52px } }
.request-row + .request-row { border-top:1px solid #263757 }
.request-diagnostic { grid-column:1/-1; color:var(--red); font-size:12px }
.cancel-request { color:var(--red) }
.request-state { display:flex; align-items:center; gap:5px }
.turn-warning { display:inline-flex; width:16px; height:16px; color:var(--amber) }
.turn-warning svg,.project-name .icn svg { width:15px; height:15px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round }
.work-section-active .session::before { background:var(--amber) }
.work-section-completed .session::before { background:var(--green) }
.work-section-failed .session::before { background:var(--red) }
.session-chat-title { font-size:13px; font-weight:650; margin:0 0 2px }
.session-technical { font-size:11px; color:var(--muted) }
.action-button.icon-button { width:24px; min-width:24px!important; height:24px; flex:0 0 24px; padding:0!important; background:transparent; border-color:transparent }
.action-button.icon-button:hover,.action-button.icon-button:focus-visible { background:#0b1529; border-color:var(--teal) }
</style>
<style>
body { background:#030e20 }
.card,.project { background:#091a32; border:0; box-shadow:none }
.session,.orphan { background:#0b203a; border:0 }
.session summary { background:#102a48 }
.session-body { border:0; background:#091b30 }
.session::before { display:none }
.work-section { background:#07182d; padding:8px 0; border-radius:8px }
.work-section-head { border:0; border-radius:5px; background:#10233b }
.request-row + .request-row { border-color:#132c45 }
.request-actions { display:flex; align-items:center; justify-content:flex-end; gap:3px }
.card { display:grid; grid-template-columns:34px 1fr; column-gap:10px; align-items:center }
.card .summary-icon { grid-row:1 / 3; color:var(--teal); background:#0b2940; border-radius:8px; padding:6px; width:34px; height:34px }
.summary-icon svg,.project-avatar svg { width:100%; height:100%; fill:none; stroke:currentColor; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round }
.card .label,.card .value { grid-column:2 }
.project-avatar { width:38px; height:38px; flex:0 0 38px; padding:7px; border:0; border-radius:8px; color:var(--purple); background:#18274b; overflow:hidden }
.project-avatar img { width:100%; height:100%; object-fit:contain; border-radius:5px }
.project-avatar:has(img) { padding:2px }
.project-avatar:focus-visible { outline:2px solid var(--teal); outline-offset:2px }
.work-section-head { margin:0 0 6px; padding:8px 10px }
.sessions { margin-inline:5px }
.session-body .request-grid { position:relative; margin-left:9px; padding-left:9px }
.session-body .request-grid::before { content:""; position:absolute; top:0; bottom:17px; left:0; width:1px; background:#28415a }
.session-body .request-row { position:relative }
.session-body .request-row::before { content:""; position:absolute; top:22px; left:-9px; width:9px; height:1px; background:#28415a }
.badge,.pill,.activity-badge,.section-count,.flag { display:inline-flex; align-items:center; justify-content:center; min-height:24px; padding:2px 8px; border:1px solid #22384d; border-radius:999px; font-size:11px; font-weight:500; line-height:18px; background:#142a40; white-space:nowrap; vertical-align:middle }
.badge.state-completed,.pill.state-completed { background:#0c302f; border-color:#153c38 }
.badge.state-running,.badge.state-active,.badge.state-queued,.badge.state-dispatching,.pill.state-running,.pill.state-active { background:#303021; border-color:#3b3b2a }
.badge.state-failed,.badge.state-rejected,.badge.state-interrupted,.pill.state-failed { background:#34232e; border-color:#402b36 }
.badge.state-closed,.badge.state-expired { background:#223044; border-color:#2a3a50 }
.activity-badge { background:#10303e; border-color:#1a3b49 }
.request-row .request-diagnostic { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; overflow-wrap:normal; max-width:100%; cursor:help }
.request-row .request-diagnostic:focus { white-space:normal; outline:1px solid var(--muted) }
.project :is(.badge,.pill,.activity-badge,.section-count,.flag) { border-color:#26394b }
</style>
<main><div class="top"><div><div class="eyebrow">AUDiaGentic · shared gateway</div><h1>Agent gateway</h1><div class="muted">Read-only operator view, redacted across all projects on this runtime</div></div><div class="pulse" id="health"><span class="dot"></span><span id="updated">Loading…</span></div></div>
<section class="cards" id="counts"></section>
<div><button type="button" id="restart-gateway" class="action-button">Restart gateway</button> <span id="restart-feedback" role="status" aria-live="polite"></span></div>
<section class="toolbar"><label>Request / session state <select id="state-filter"><option value="all">All states</option></select></label><label><input id="show-closed" type="checkbox"> Show closed</label><label><input id="show-empty" type="checkbox"> Show empty</label><label>Layout <select id="layout-filter"><option value="columns">Columns</option><option value="rows">Rows</option></select></label><label>Recent window <input id="recent-window" type="number" min="1" step="1" aria-label="Recent window in seconds"> sec</label><button id="apply-window" type="button">Apply</button><label>Auto-collapse after <input id="collapse-hours" type="number" min="0" max="8760" step="0.5" aria-label="Auto-collapse inactive sessions after hours"> hours (0 = off)</label><span class="muted" id="visible-summary"></span></section>
<div id="request-action-feedback" role="status" aria-live="polite"></div><section id="projects"></section></main>
<script>
const endpoint=new URL(__SNAPSHOT_PATH__,window.location.href);
const initialRecent=new URLSearchParams(window.location.search).get('recent-seconds'); if(initialRecent) endpoint.searchParams.set('recent-seconds',initialRecent);
const stateFilter=document.getElementById('state-filter'); const showClosed=document.getElementById('show-closed'); const showEmpty=document.getElementById('show-empty'); const layoutFilter=document.getElementById('layout-filter'); const recentWindow=document.getElementById('recent-window'); let latest=null; let refreshGeneration=0; let refreshInFlight=false;
const COLLAPSED_SESSIONS_KEY='gateway-dashboard-collapsed-sessions'; let collapsedSessionIds=new Set(); try { const saved=JSON.parse(localStorage.getItem(COLLAPSED_SESSIONS_KEY)||'[]'); if(Array.isArray(saved)) collapsedSessionIds=new Set(saved.filter(id=>typeof id==='string').slice(-500)); } catch (_) {}
function persistCollapsedSessions() { try { localStorage.setItem(COLLAPSED_SESSIONS_KEY,JSON.stringify([...collapsedSessionIds].slice(-500))); } catch (_) {} }
const EXPANDED_SESSIONS_KEY='gateway-dashboard-expanded-sessions'; const COLLAPSE_HOURS_KEY='gateway-dashboard-collapse-hours';
let expandedSessionIds=new Set(); let collapseHours=2;
const SECTION_CHOICES_KEY='gateway-dashboard-section-choices';let sectionChoices=new Map();
try{const saved=JSON.parse(localStorage.getItem(SECTION_CHOICES_KEY)||'[]');if(Array.isArray(saved))sectionChoices=new Map(saved.filter(x=>Array.isArray(x)&&typeof x[0]==='string'&&typeof x[1]==='boolean').slice(-500));const old=JSON.parse(localStorage.getItem('gateway-dashboard-expanded-expired-projects')||'[]');if(Array.isArray(old))for(const id of old){const key=JSON.stringify([id,'Expired']);if(typeof id==='string'&&!sectionChoices.has(key))sectionChoices.set(key,true);}localStorage.setItem(SECTION_CHOICES_KEY,JSON.stringify([...sectionChoices].slice(-500)));localStorage.removeItem('gateway-dashboard-expanded-expired-projects');}catch(_){}
function bindSectionToggles(){document.querySelectorAll('.section-toggle').forEach(button=>button.addEventListener('click',event=>{
  event.preventDefault();sectionChoices.set(button.dataset.sectionKey,button.getAttribute('aria-expanded')!=='true');
  try{localStorage.setItem(SECTION_CHOICES_KEY,JSON.stringify([...sectionChoices].slice(-500)));}catch(_){}
  if(latest)draw(latest);
}));}
function collapsibleSection(project,title,heading,body){
  const key=JSON.stringify([String(project['project-id']||project.name),title]);
  const expanded=sectionChoices.has(key)?sectionChoices.get(key):title==='Active';
  return `<section class="work-section work-section-${title.toLowerCase().replaceAll(' ','-')}"><button type="button" class="work-section-head section-toggle" style="width:100%" data-section-key="${esc(key)}" aria-expanded="${expanded}"><span aria-hidden="true">${expanded?'▾':'▸'}</span>${heading}</button><div${expanded?'':' hidden'}>${body}</div></section>`;
}
try { const saved=JSON.parse(localStorage.getItem(EXPANDED_SESSIONS_KEY)||'[]');if(Array.isArray(saved))expandedSessionIds=new Set(saved.filter(id=>typeof id==='string').slice(-500));const hours=localStorage.getItem(COLLAPSE_HOURS_KEY);if(hours!==null&&hours.trim()!==''&&Number.isFinite(Number(hours))&&Number(hours)>=0&&Number(hours)<=8760)collapseHours=Number(hours); }catch(_){}
const collapseInput=document.getElementById('collapse-hours');collapseInput.value=collapseHours;
collapseInput.addEventListener('change',()=>{const hours=Number(collapseInput.value);if(!collapseInput.value.trim()||!Number.isFinite(hours)||hours<0||hours>8760){collapseInput.value=collapseHours;return;}if(hours===collapseHours)return;collapseHours=hours;try{localStorage.setItem(COLLAPSE_HOURS_KEY,String(hours));}catch(_){}if(latest)draw(latest);});
function sessionShouldOpen(session,rows) {
  const id=String(session['session-id']||'');
  if(collapsedSessionIds.has(id))return false;
  if(expandedSessionIds.has(id)||collapseHours===0)return true;
  if(session['turn-active']||rows.some(r=>ACTIVE_REQUEST_STATES.has(r.state)))return true;
  const last=Math.max(recent(session),...rows.map(recent));
  return !Number.isFinite(last)||Date.now()-last<collapseHours*3600000;
}
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateTimeFmt=new Intl.DateTimeFormat(undefined,{day:'numeric',month:'short',hour:'numeric',minute:'2-digit'}); const clockFmt=new Intl.DateTimeFormat(undefined,{timeStyle:'medium'}); const stamp=x=>{if(x===undefined||x===null||x===''||(typeof x==='number'&&!Number.isFinite(x)))return ''; const d=new Date(x); return Number.isFinite(d.getTime())?dateTimeFmt.format(d):''}; const isClosed=s=>['closed','expired'].includes(s?.state); const timestamp=x=>{const value=Date.parse(x||''); return Number.isFinite(value)?value:-Infinity}; const recent=x=>Math.max(...['updated-at','last-activity-at','closed-at','created-at'].map(key=>timestamp(x?.[key])));
const bySessionId=(a,b)=>String(a?.['session-id']||'').localeCompare(String(b?.['session-id']||'')); const byRequestId=(a,b)=>String(a?.['request-id']||'').localeCompare(String(b?.['request-id']||'')); const byRequestNewest=(a,b)=>timestamp(b?.['created-at'])-timestamp(a?.['created-at'])||byRequestId(a,b); const groupCreated=g=>Math.max(...(g[1]||[]).map(row=>timestamp(row?.['created-at']))); const groupUpdated=g=>Math.max(timestamp(g[0]?.['updated-at']),...(g[1]||[]).map(row=>timestamp(row?.['updated-at']))); const byGroupNewest=(a,b)=>groupCreated(b)-groupCreated(a)||bySessionThenRequest(a,b); const byGroupUpdated=(a,b)=>groupUpdated(b)-groupUpdated(a)||bySessionThenRequest(a,b); const SESSION_TERMINAL_STATES=new Set(['closed','expired','failed']); const bySessionStateThenId=(a,b)=>{const stateOrder=Number(SESSION_TERMINAL_STATES.has(a?.state))-Number(SESSION_TERMINAL_STATES.has(b?.state)); return stateOrder||bySessionId(a,b)}; const bySessionThenRequest=(a,b)=>{const sessionOrder=bySessionId(a?.[0],b?.[0]); return sessionOrder||byRequestId(a?.[1]?.[0],b?.[1]?.[0])}; const stateClass=s=>'state-'+String(s||'').replaceAll('_','-');
const ACTIVE_REQUEST_STATES=new Set(['queued','dispatching','running']); const FAILED_REQUEST_STATES=new Set(['failed','rejected','interrupted','timed-out','expired','abandoned']);
function badge(state) { return `<span class="badge ${stateClass(state)}">${esc(state||'unknown')}</span>`; }
function queueSummary(queues) { const entries=Object.entries(queues||{}); if(!entries.length) return ''; return entries.map(([profile,depth])=>{const d=depth||{}; const parts=[]; if(d.pending) parts.push(`${d.pending} pending`); if(d.active_running) parts.push(`${d.active_running} running`); if(d.idle) parts.push(`${d.idle} idle`); return `${profile}: ${parts.join(', ')||'idle'}`}).join(' · '); }
function sideEffectFlag(r) { const side=r.diagnostics?.['side-effect-state']; if(r.state==='completed'||((!FAILED_REQUEST_STATES.has(r.state)&&r.state!=='cancelled')||side!=='may-have-started')) return ''; return `<span class="turn-warning" title="The provider may have received this turn; verify the provider session before retrying." aria-label="Provider turn uncertain"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 10 18H2zM12 9v5m0 3v1"/></svg></span>`; }
function activityLabel(r) { if(!ACTIVE_REQUEST_STATES.has(r.state)) return Number.isInteger(r['activity-sequence'])?`<span class="activity-badge">Activity Count #${r['activity-sequence']}</span>`:''; const phase=r['activity-type']||''; const fallback=phase||(r.state==='queued'?'waiting':(ACTIVE_REQUEST_STATES.has(r.state)?r.state:'')); const seq=r['activity-sequence']; if(!fallback)return ''; return `<span class="activity-badge"><span class="activity-kind">${esc(fallback)}</span>${seq!==undefined?`<span class="activity-seq">#${esc(seq)}</span>`:''}</span>`; }
const focusEndpoint=__FOCUS_PATH__; const purgeEndpoint=__PURGE_PATH__; const focusToken=__FOCUS_TOKEN__;
const restartEndpoint=focusEndpoint.slice(0,focusEndpoint.lastIndexOf('/'))+'/restart';
document.getElementById('restart-gateway').addEventListener('click',async function(){
  if(!window.confirm('Restart the gateway? Stored sessions and history are preserved. Restart is refused while work is active.'))return;
  this.disabled=true;
  const feedback=document.getElementById('restart-feedback');
  const headers={'Content-Type':'application/json','X-AudiaGentic-Dashboard-Token':focusToken};
  feedback.textContent='Requesting restart…';
  try {
    const response=await fetch(restartEndpoint,{method:'POST',headers,body:'{}',signal:AbortSignal.timeout(15000)});
    const body=await response.json();
    if(!response.ok||!body.result?.restarting)throw new Error(body.error?.message||'Restart refused; check active work.');
    feedback.textContent='Restarting — waiting for gateway…';
    for(let attempt=0;attempt<60;attempt++){
      await new Promise(resolve=>setTimeout(resolve,1000));
      try {
        const probe=await fetch(restartEndpoint,{headers,cache:'no-store',signal:AbortSignal.timeout(2000)});
        if(!probe.ok)continue;
        const health=await probe.json();
        if(health.state==='running'&&health['owner-epoch']!==body.result['owner-epoch']){window.location.reload();return;}
      }catch(_){}
    }
    feedback.textContent='Gateway has not reconnected yet. Reload to check; inspect service logs if it stays offline.';
  }catch(error){feedback.textContent=error.message||'Restart could not be confirmed. Reload to check gateway status.';}
  finally{this.disabled=false;}
});
const focusIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3h7v7M21 3 11 13M10 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/></svg>';
const purgeIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';
function summaryIcon(label) {
  const paths={Projects:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',Sessions:'M3 4h14v11H7l-4 4zM10 19h8l3 3V9',Running:'m7 3 15 9-15 9z',Failed:'m12 3 10 18H2zM12 9v5M12 17v1','Providers loaded':'M8 3v5M16 3v5M5 8h14v4a7 7 0 0 1-7 7v3M5 12a7 7 0 0 0 7 7','Provider errors':'m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6zM12 7v6M12 16v1'};
  return `<span class="summary-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="${paths[label]||paths.Projects}"/></svg></span>`;
}
function projectAvatar(project) {
  if(!project['project-id'])return summaryIcon('Projects');
  const url=new URL(focusEndpoint.slice(0,focusEndpoint.lastIndexOf('/'))+'/project-image',location.href);
  url.searchParams.set('project-id',project['project-id']);url.searchParams.set('v',project['image-version']||'');
  return `<button class="project-avatar" type="button" data-project-id="${esc(project['project-id'])}" aria-label="Choose project image for ${esc(project.name)}" title="Choose project image">${project['image-version']?`<img src="${esc(url.href)}" alt="">`:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h7l2 2h9v11H3zM3 7V4h7l2 3h6"/></svg>'}</button>`;
}
document.addEventListener('click',event=>{
  const button=event.target.closest('.project-avatar');if(!button)return;
  const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp';
  input.addEventListener('change',async()=>{
    const file=input.files[0];if(!file)return;
    const feedback=document.getElementById('request-action-feedback');
    try {
      if(file.size>5*1024*1024||!['image/png','image/jpeg','image/webp'].includes(file.type))throw new Error('Choose a PNG, JPEG or WebP image under 5 MiB.');
      const bitmap=await createImageBitmap(file);
      const canvas=document.createElement('canvas');canvas.width=128;canvas.height=128;
      const scale=Math.min(128/bitmap.width,128/bitmap.height);
      canvas.getContext('2d').drawImage(bitmap,(128-bitmap.width*scale)/2,(128-bitmap.height*scale)/2,bitmap.width*scale,bitmap.height*scale);bitmap.close();
      const png=canvas.toDataURL('image/png').split(',')[1];
      const response=await fetch(focusEndpoint.slice(0,focusEndpoint.lastIndexOf('/'))+'/project-image',{method:'POST',headers:{'Content-Type':'application/json','X-AudiaGentic-Dashboard-Token':focusToken},body:JSON.stringify({'project-id':button.dataset.projectId,png}),signal:AbortSignal.timeout(15000)});
      const body=await response.json();if(!response.ok)throw new Error(body.error?.message||'Project image upload failed');
      feedback.textContent='Project image saved';await refresh();
    }catch(error){feedback.textContent=error.message||'Project image upload failed';}
  });input.click();
});
const cancelIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m8 8 8 8m0-8-8 8"/></svg>';
function cancelControl(r) { return ACTIVE_REQUEST_STATES.has(r.state)?` <button type="button" class="action-button icon-button cancel-request" data-request-id="${esc(r['request-id'])}" aria-label="Cancel request" title="Cancel request">${cancelIcon}</button>`:''; }
async function cancelRequest(button) {
  if(!window.confirm('Cancel this request? Its history will be retained.'))return;
  button.disabled=true;
  const feedback=document.getElementById('request-action-feedback');
  feedback.textContent='Requesting cancellation…';
  try {
    const response=await fetch(focusEndpoint.slice(0,focusEndpoint.lastIndexOf('/'))+'/cancel-request',{method:'POST',headers:{'Content-Type':'application/json','X-AudiaGentic-Dashboard-Token':focusToken},body:JSON.stringify({'request-id':button.dataset.requestId}),signal:AbortSignal.timeout(15000)});
    const body=await response.json();
    if(!response.ok)throw new Error(body.error?.message||'Cancellation failed');
    feedback.textContent='Cancellation requested for '+button.dataset.requestId;
    await refresh();
  }catch(error){feedback.textContent=error.message||'Cancellation could not be confirmed';}
  finally{button.disabled=false;}
}
function chatLink(r) { if(!r['focus-tab-available']) return ''; return ` <button type="button" class="action-button icon-button icon-action focus-chat" data-request-id="${esc(r['request-id'])}" aria-label="Open or focus GPT tab" title="Open the retained GPT tab, or focus it if already open">${focusIcon}</button>`; }
function setFeedback(button, text) { button.classList.add('feedback'); button.title=text; button.setAttribute('aria-label',text); setTimeout(()=>button.classList.remove('feedback'),1800); }
async function focusChat(button) { const id=button.dataset.requestId; button.disabled=true; try { const response=await fetch(focusEndpoint,{method:'POST',headers:{'Content-Type':'application/json','X-AudiaGentic-Dashboard-Token':focusToken},body:JSON.stringify({'request-id':id})}); const body=await response.json(); const result=body.result||{}; setFeedback(button,result.reason==='conversation-tab-opened'?'GPT tab opened':(result.outcome==='focused'?'GPT tab focused':(result.reason||result.outcome||'GPT tab unavailable'))); } catch(error) { setFeedback(button,'GPT tab unavailable'); } finally { setTimeout(()=>{button.disabled=false;},1200); } }
async function purgeSession(button) { const id=button.dataset.sessionId; if(!window.confirm('Purge this session and all gateway request data? This cannot be undone.')) return; button.disabled=true; try { const response=await fetch(purgeEndpoint,{method:'POST',headers:{'Content-Type':'application/json','X-AudiaGentic-Dashboard-Token':focusToken},body:JSON.stringify({'session-id':id})}); const body=await response.json(); const result=body.result||{}; setFeedback(button,result.outcome==='purged'?'Session purged':(result.reason||result.outcome||'Purge unavailable')); if(result.outcome==='purged') setTimeout(refresh,400); } catch(error) { setFeedback(button,'Purge unavailable'); } finally { setTimeout(()=>{button.disabled=false;},1200); } }
function bindFocusButtons() { document.querySelectorAll('.cancel-request').forEach(button=>button.addEventListener('click',()=>cancelRequest(button))); document.querySelectorAll('.focus-chat').forEach(button=>button.addEventListener('click',()=>focusChat(button))); document.querySelectorAll('.purge-session').forEach(button=>button.addEventListener('click',()=>purgeSession(button))); }
function bindSessionToggles() { document.querySelectorAll('details.session[data-session-id] > summary').forEach(summary=>summary.addEventListener('click',event=>{if(event.target.closest('button,a'))return; event.preventDefault(); const session=summary.parentElement; const id=session.dataset.sessionId; const opening=!session.open; if(opening){collapsedSessionIds.delete(id);expandedSessionIds.add(id);}else{expandedSessionIds.delete(id);collapsedSessionIds.add(id);} persistCollapsedSessions(); try{localStorage.setItem(EXPANDED_SESSIONS_KEY,JSON.stringify([...expandedSessionIds].slice(-500)));}catch(_){} if(latest)draw(latest); })); }
function executionSummary(profile, provider, model) { const identity=[]; if(profile)identity.push(profile); if(provider&&provider!==profile)identity.push(provider); const left=identity.join(' · '); return model&&!identity.includes(model)?left+(left?' / ':'')+model:left; }
function requestDiagnostic(r) {
  if(r.state==='completed') return '';
  const d=r.diagnostics||{};
  const clean=value=>typeof value==='string'&&!['','none',r.state].includes(value.trim().toLowerCase())?value.trim():'';
  const parts=[r.error?.code||d['failure-code'],r.error?.message||d.classification,d.recovery?.disposition].map(clean).filter(Boolean);
  return [...new Set(parts)].join(' · ');
}
function requestRows(rows, includeExecution=true) {
  return rows.slice().sort(byRequestNewest).map(r=>{
    const execution=includeExecution?executionSummary(r['execution-profile-id'],r['resolved-provider-id'],r['resolved-model-id']):'';
    const title=includeExecution&&r['provider-chat-title']?r['provider-chat-title']:'';
    const diagnostic=requestDiagnostic(r);
    return `<div class="request-row"><div class="request-identity"><code class="request-id">${esc(r['request-id'])}</code>${title?`<span class="request-title" title="${esc(title)}">${esc(title)}</span>`:''}${execution?`<span class="request-execution" title="${esc(execution)}">${esc(execution)}</span>`:''}</div><div class="request-state">${badge(r.state)}${sideEffectFlag(r)}</div><div class="request-meta">${activityLabel(r)}</div><div class="request-meta request-updated">${stamp(recent(r))}</div><div class="request-actions">${cancelControl(r)}${chatLink(r)}</div>${diagnostic?`<div class="request-diagnostic" tabindex="0" title="${esc(diagnostic)}" aria-label="${esc(diagnostic)}">${esc(diagnostic)}</div>`:''}</div>`;
  }).join('');
}
function sessionActivitySummary(session) {
  const turns=session['turn-count']||0;
  return [turns+' Requests',session['pending-turns']>0?session['pending-turns']+' pending':'',session['turn-active']?'turn active':''].filter(Boolean).join(' · ');
}
function matchesState(session, rows) { const wanted=stateFilter.value; return wanted==='all'||session.state===wanted||rows.some(r=>r.state===wanted); }
function matchesRequest(row) { return stateFilter.value==='all'||row.state===stateFilter.value; }
function sessionCard(session, rows, empty=false, allRows=rows) { const sessionId=String(session['session-id']||''); const open=sessionShouldOpen(session,allRows)?' open':''; const purgeable=!allRows.some(r=>ACTIVE_REQUEST_STATES.has(r.state))&&!session['turn-active']&&!(session['pending-turns']>0); const purge=purgeable?`<button type="button" class="action-button icon-button purge-session" data-session-id="${esc(sessionId)}" aria-label="Purge session" title="Permanently remove this session and all gateway data">${purgeIcon}</button>`:''; const execution=executionSummary(esc(session['execution-profile-id']||''),esc(session['provider-id']||''),esc(session['model-id']||'')); const title=session['provider-chat-title']?`<div class="session-chat-title" title="${esc(session['provider-chat-title'])}">${esc(session['provider-chat-title'])}</div>`:''; return `<details class="session ${stateClass(session.state)}" data-session-id="${esc(sessionId)}"${open}><summary><div class="session-head"><div class="session-identity">${title}<div class="${title?'session-technical':'session-primary'}"><code>${esc(sessionId)}</code>${execution?` <span class="session-profile"> · ${execution}</span>`:''}</div></div><div class="session-actions">${badge(session.state)} <span class="muted">${esc(sessionActivitySummary(session))}</span>${purge}</div></div></summary><div class="session-body"><div class="request-grid">${empty?'<div class="muted">No matching requests</div>':requestRows(rows,false)}</div></div></details>`; }
function requestGroup(state) { if(ACTIVE_REQUEST_STATES.has(state)) return 'active'; if(FAILED_REQUEST_STATES.has(state)) return 'failed'; return 'completed'; }
function projectView(project) {
  const grouped=new Map(); const requests=(project.requests||[]);
  requests.forEach(r=>{const id=r['session-id']; if(id){const existing=grouped.get(id)||[]; existing.push(r); grouped.set(id,existing)}});
  const knownSessionIds=new Set((project.sessions||[]).map(s=>s['session-id'])); const wanted=stateFilter.value;
  const sessionGroups=(project.sessions||[]).map(s=>{const allRows=grouped.get(s['session-id'])||[]; const sessionMatches=wanted==='all'||s.state===wanted; const rows=sessionMatches?allRows:allRows.filter(r=>r.state===wanted); return {session:s,allRows,rows}}).filter(group=>{const s=group.session; const hasRows=group.rows.length>0; return (showClosed.checked||!isClosed(s)||hasRows)&&(showEmpty.checked||hasRows)&& (wanted==='all'||s.state===wanted||hasRows)});
  const sections={active:[],closed:[],expired:[]};
  sessionGroups.forEach(({session,rows,allRows})=>{
    const section=session.state==='expired'?'expired':SESSION_TERMINAL_STATES.has(session.state)?'closed':'active';
    sections[section].push([session,rows,allRows]);
  });
  const unbound=requests.filter(r=>(!r['session-id']||!knownSessionIds.has(r['session-id']))&&matchesRequest(r));
  if(!Object.values(sections).some(groups=>groups.length)&&!unbound.length)return '';
  const tally={}; requests.forEach(r=>{const group=requestGroup(r.state);tally[group]=(tally[group]||0)+1}); const pills=Object.entries(tally).map(([state,n])=>`<span class="pill ${stateClass(state)}">${n} ${esc(state)}</span>`).join('');
  const section=(title,groups)=>{
    if(!groups.length)return '';
    const orderedGroups=groups.slice().sort(title==='Active'?byGroupNewest:byGroupUpdated);
    const body=`<div class="sessions">${orderedGroups.map(([s,rows,allRows])=>sessionCard(s,rows,!rows.length,allRows)).join('')}</div>`;
    const heading=`<h3>${title}</h3><span class="section-count">${groups.length} sessions</span>`;
    return collapsibleSection(project,title,heading,body);
  };
  const unboundSection=unbound.length?collapsibleSection(project,'Unassigned requests','<h3>Unassigned requests</h3>',`<div class="orphan">${requestRows(unbound)}</div>`):'';
  return `<section class="project"><div class="project-head"><div><div class="project-name">${projectAvatar(project)}${esc(project.name)}</div>${queueSummary(project.queues)?`<div class="queue">${esc(queueSummary(project.queues))}</div>`:''}</div><div class="pills">${pills}</div></div>${section('Active',sections.active)}${section('Closed',sections.closed)}${section('Expired',sections.expired)}${unboundSection}</section>`;
}
function populateStates(snapshot) { const prior=stateFilter.value; const states=new Set(); (snapshot.projects||[]).forEach(p=>{(p.sessions||[]).forEach(s=>states.add(s.state));(p.requests||[]).forEach(r=>states.add(r.state))}); stateFilter.innerHTML='<option value="all">All states</option>'+[...states].filter(Boolean).sort().map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join(''); stateFilter.value=[...stateFilter.options].some(o=>o.value===prior)?prior:'all'; }
function draw(snapshot) {
  latest=snapshot; populateStates(snapshot);
  const chosenLayout=localStorage.getItem('gateway-dashboard-layout')||'columns'; layoutFilter.value=chosenLayout;
  const dashboard=snapshot.dashboard||{}; if(document.activeElement!==recentWindow) recentWindow.value=dashboard['recent-window-seconds']??'';
  document.getElementById('updated').textContent='Updated '+clockFmt.format(new Date());
  const diag=snapshot['provider-diagnostics']||{}; const errorCount=(diag['provider-load-errors']||[]).length;
  document.getElementById('health').classList.toggle('stale', errorCount>0);
  const sessionCount=(snapshot.projects||[]).reduce((n,p)=>n+(p.sessions||[]).length,0);
  const runningCount=(snapshot.counts||{}).running||0;
  const failedCount=['failed','rejected','interrupted','timed-out','expired','abandoned'].reduce((total,state)=>total+((snapshot.counts||{})[state]||0),0);
  document.getElementById('counts').innerHTML=[
    `<div class="card">${summaryIcon('Projects')}<div class="label">Projects</div><div class="value info">${(snapshot.projects||[]).length}</div></div>`,
    `<div class="card">${summaryIcon('Sessions')}<div class="label">Sessions</div><div class="value info">${sessionCount}</div></div>`,
    `<div class="card">${summaryIcon('Running')}<div class="label">Running</div><div class="value warn">${runningCount}</div></div>`,
    `<div class="card">${summaryIcon('Failed')}<div class="label">Failed</div><div class="value bad">${failedCount}</div></div>`,
    `<div class="card">${summaryIcon('Providers loaded')}<div class="label">Providers loaded</div><div class="value good">${diag['providers-loaded']??0}</div></div>`,
    `<div class="card">${summaryIcon('Provider errors')}<div class="label">Provider errors</div><div class="value ${errorCount?'bad':'good'}">${errorCount}</div></div>`,
  ].join('');
  const projects=(snapshot.projects||[]).map(projectView).join('');
  const projectsElement=document.getElementById('projects'); projectsElement.className='layout-'+chosenLayout; projectsElement.innerHTML=projects||'<div class="empty">No sessions match these filters.</div>';
  bindFocusButtons(); bindSessionToggles(); bindSectionToggles();
  const visible=document.querySelectorAll('#projects .session').length;
  document.getElementById('visible-summary').textContent=`${visible} sessions visible · newest requests first · ${dashboard['recent-window-seconds']??''} sec window`;
}
async function refresh(){if(refreshInFlight)return; const generation=++refreshGeneration; refreshInFlight=true; try{const response=await fetch(endpoint,{cache:'no-store'}); const snapshot=await response.json(); if(generation===refreshGeneration) draw(snapshot);}catch(error){if(generation===refreshGeneration){document.getElementById('health').classList.add('stale');document.getElementById('updated').textContent='Dashboard refresh failed: '+error}}finally{refreshInFlight=false;}}
function applyWindow(){const value=recentWindow.value.trim(); if(value){const parsed=Number.parseInt(value,10); if(!Number.isInteger(parsed)||parsed<1)return; endpoint.searchParams.set('recent-seconds',String(parsed));}else endpoint.searchParams.delete('recent-seconds'); const pageUrl=new URL(window.location.href); if(endpoint.searchParams.has('recent-seconds')) pageUrl.searchParams.set('recent-seconds',endpoint.searchParams.get('recent-seconds')); else pageUrl.searchParams.delete('recent-seconds'); window.history.replaceState(null,'',pageUrl.pathname+(pageUrl.search?`?${pageUrl.searchParams}`:'')+pageUrl.hash); refresh();}
stateFilter.addEventListener('change',()=>latest&&draw(latest)); showClosed.addEventListener('change',()=>latest&&draw(latest)); showEmpty.addEventListener('change',()=>latest&&draw(latest)); layoutFilter.addEventListener('change',()=>{localStorage.setItem('gateway-dashboard-layout',layoutFilter.value); latest&&draw(latest)}); document.getElementById('apply-window').addEventListener('click',applyWindow); refresh(); setInterval(refresh,3000);
</script></main>""".replace("__SNAPSHOT_PATH__", source).replace("__FOCUS_PATH__", focus_source).replace("__PURGE_PATH__", purge_source).replace("__FOCUS_TOKEN__", token_source)
    return html.encode("utf-8")


__all__ = ["dashboard_snapshot", "render_dashboard_html"]

