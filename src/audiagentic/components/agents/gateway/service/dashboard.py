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

DEFAULT_RECENT_WINDOW_SECONDS = 12 * 60 * 60
MAX_RECENT_WINDOW_SECONDS = 30 * 24 * 60 * 60
RECENT_WINDOW_ENV = "AUDIAGENTIC_GATEWAY_DASHBOARD_RECENT_SECONDS"
_ACTIVE_REQUEST_STATES = frozenset({"queued", "dispatching", "running"})
_ACTIVE_SESSION_STATES = frozenset({"active", "closing"})


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
            key=_most_recent,
            reverse=True,
        )
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
            key=_most_recent,
            reverse=True,
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
            if row["state"] in {"failed", "rejected", "interrupted"}
        )
        projects.append(
            {
                "name": root.name,
                "config-status": known.config_status,
                "last-seen-at": known.last_seen_at.isoformat(),
                "queues": api.get_queue_manager().project_queue_depths(root),
                "sessions": session_rows,
                "requests": request_rows,
            }
        )

    projects.sort(key=lambda project: project["name"].casefold())
    requests.sort(key=_most_recent, reverse=True)
    failures.sort(key=_most_recent, reverse=True)
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
        "latest-transition", "error", "provider-chat-url",
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
* { box-sizing:border-box } body { background:radial-gradient(circle at 85% 0,#1c3860 0,var(--bg) 42%); color:var(--text); font:14px/1.45 system-ui,sans-serif; margin:0; padding:28px; }
main { max-width:1500px; margin:auto } h1,h2,h3 { margin:0 } h1 { font-size:28px; font-weight:750; letter-spacing:-.02em } h2 { font-size:17px; margin:24px 0 10px } h3 { font-size:14px } .muted { color:var(--muted) } .eyebrow { color:var(--teal); font-size:11px; font-weight:700; letter-spacing:.14em; text-transform:uppercase }
.top,.toolbar,.session-head,.project-head { display:flex; gap:12px; align-items:center; justify-content:space-between; flex-wrap:wrap } .toolbar { background:#0e1930cc; border:1px solid var(--line); border-radius:12px; padding:12px; margin:18px 0 }
.pulse { display:flex; gap:8px; align-items:center; color:var(--green); font-weight:650 } .dot { width:9px; height:9px; border-radius:50%; background:var(--green); box-shadow:0 0 14px var(--green) } .pulse.stale .dot { background:var(--amber); box-shadow:0 0 14px var(--amber) } .pulse.stale { color:var(--amber) }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(128px,1fr)); gap:10px; margin:18px 0 }.card,.project,.session,.orphan { background:linear-gradient(145deg,var(--panel2),#10182c); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow) }.card { padding:13px }.card .label { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.08em }.value { font-size:25px; font-weight:750; margin-top:3px }.value.good { color:var(--green) }.value.warn { color:var(--amber) }.value.bad { color:var(--red) }.value.info { color:var(--teal) }
.project { padding:16px; margin:14px 0 }.project-head { margin-bottom:12px }.project-name { display:flex; align-items:center; gap:8px; font-weight:750; font-size:15px }.project-name .icn { color:var(--purple) }.pills { display:flex; gap:6px; flex-wrap:wrap }.pill { border-radius:999px; padding:3px 9px; font-size:11px; font-weight:650; border:1px solid var(--line); color:var(--muted) }.pill.state-completed { color:var(--green); border-color:#254a37 }.pill.state-failed,.pill.state-rejected,.pill.state-interrupted { color:var(--red); border-color:#5a2a30 }.pill.state-queued,.pill.state-running,.pill.state-dispatching,.pill.state-active { color:var(--amber); border-color:#5a4a24 }
#projects.layout-columns { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr)); gap:14px; align-items:start } #projects.layout-columns .project { margin:0; min-width:0 } #projects.layout-rows { display:block } .work-section { margin-top:12px } .work-section > h3 { color:var(--muted); font-size:11px; letter-spacing:.1em; text-transform:uppercase; margin:0 0 7px } .request-grid { display:grid; gap:6px } .request-header,.request-row { display:grid; grid-template-columns:minmax(150px,1.3fr) minmax(105px,.8fr) minmax(125px,1fr) minmax(125px,1fr) minmax(140px,1.4fr); gap:8px; align-items:center } .request-header { color:var(--muted); font-size:10px; font-weight:650; letter-spacing:.06em; text-transform:uppercase; padding:0 9px 2px } .request-header > div,.request-row > div { min-width:0; overflow-wrap:anywhere } .request-row { padding:8px 9px; border:1px solid #263757; border-radius:8px; background:#101a30 } .request-row .request-identity { display:flex; gap:5px; align-items:center; flex-wrap:nowrap; min-width:0 } .request-row .request-id { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap } .request-row .request-meta { color:var(--muted); font-size:12px } .request-row .request-error { color:var(--red); font-size:12px } .session-actions { display:flex; gap:5px; align-items:center; justify-content:flex-end } .icon-button { min-width:30px !important; width:30px; height:28px; flex:0 0 30px; padding:4px !important; font-size:16px !important } .icon-button svg { width:15px; height:15px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round } .icon-button.feedback { border-color:var(--teal); color:var(--teal) }
.queue { font:12px ui-monospace,monospace; color:var(--muted); margin-top:2px }.sessions { display:grid; gap:10px }.session { overflow:hidden; position:relative; border-left:3px solid var(--line) }.session.state-completed { border-left-color:var(--green) }.session.state-failed,.session.state-rejected,.session.state-interrupted { border-left-color:var(--red) }.session.state-queued,.session.state-running,.session.state-dispatching,.session.state-active { border-left-color:var(--amber) }.session summary { cursor:pointer; list-style:none; padding:12px 14px }.session summary::-webkit-details-marker { display:none }.session-head { display:grid; grid-template-columns:minmax(210px,1fr) auto auto; align-items:center }.session-body { border-top:1px solid var(--line); padding:0 14px 12px }
.badge { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 8px; font-size:12px; white-space:nowrap }.state-completed { color:var(--green) }.state-failed,.state-rejected,.state-interrupted { color:var(--red) }.state-queued,.state-running,.state-dispatching,.state-active { color:var(--amber) }.live { color:var(--amber); font-size:12px; font-weight:650 } code { color:var(--teal); font:12px ui-monospace,SFMono-Regular,Consolas,monospace }
.flag { display:inline-block; background:#1c2740; border:1px solid var(--line); color:var(--muted); border-radius:6px; padding:1px 7px; font-size:11px; margin-left:5px }.flag.alert { color:var(--red); border-color:#5a2a30; background:#2a1418; font-weight:650 }.flag.warn { color:var(--amber); border-color:#5a4a24; background:#241c10; font-weight:650 }.flag.progress { color:var(--amber); border-color:#5a4a24; background:#241c10 }
.flag.stale { color:var(--muted); border-style:dashed }
table { width:100%; border-collapse:collapse } .request-table { table-layout:fixed } .request-table th,.request-table td { overflow-wrap:anywhere; word-break:break-word } .session-request-table th:nth-child(1),.session-request-table td:nth-child(1) { width:24% } .session-request-table th:nth-child(2),.session-request-table td:nth-child(2) { width:22% } .session-request-table th:nth-child(3),.session-request-table td:nth-child(3) { width:18% } .session-request-table th:nth-child(4),.session-request-table td:nth-child(4) { width:16% } .session-request-table th:nth-child(5),.session-request-table td:nth-child(5) { width:20% } .one-shot-request-table th:nth-child(1),.one-shot-request-table td:nth-child(1) { width:21% } .one-shot-request-table th:nth-child(2),.one-shot-request-table td:nth-child(2) { width:18% } .one-shot-request-table th:nth-child(3),.one-shot-request-table td:nth-child(3) { width:15% } .one-shot-request-table th:nth-child(4),.one-shot-request-table td:nth-child(4) { width:18% } .one-shot-request-table th:nth-child(5),.one-shot-request-table td:nth-child(5) { width:12% } .one-shot-request-table th:nth-child(6),.one-shot-request-table td:nth-child(6) { width:16% } th,td { padding:8px 5px; border-bottom:1px solid #263757; text-align:left; vertical-align:top } th { color:var(--muted); font-weight:600; font-size:12px } tr:last-child td { border-bottom:0 }.error { color:var(--red); font-size:12px }.orphan { padding:14px; margin:14px 0 } select,label { color:var(--text) } select { background:#0b1529; border:1px solid var(--line); border-radius:7px; padding:6px }
.empty { color:var(--muted); padding:24px; text-align:center; border:1px dashed var(--line); border-radius:12px }
input[type=number],button,.action-button { background:#0b1529; border:1px solid var(--line); border-radius:7px; color:var(--text); padding:6px 8px } input[type=number] { width:100px } button,.action-button { cursor:pointer } button:hover,.action-button:hover { border-color:var(--teal) } .action-button { box-sizing:border-box; display:inline-flex; align-items:center; justify-content:center; font-family:inherit; font-size:11px; height:28px; min-width:88px; line-height:1.2; white-space:nowrap; text-decoration:none; vertical-align:middle } .chat-link { color:var(--teal) } .chat-link:hover { text-decoration:none } .purge-session { color:var(--red) }
@media (max-width:700px) { body { padding:14px }.session-head { grid-template-columns:1fr }.session-body { overflow-x:auto } th:nth-child(3),td:nth-child(3) { display:none } }
</style>
<main><div class="top"><div><div class="eyebrow">AUDiaGentic · shared gateway</div><h1>Agent gateway</h1><div class="muted">Read-only operator view, redacted across all projects on this runtime</div></div><div class="pulse" id="health"><span class="dot"></span><span id="updated">Loading…</span></div></div>
<section class="cards" id="counts"></section>
<section class="toolbar"><label>Request / session state <select id="state-filter"><option value="all">All states</option></select></label><label><input id="show-closed" type="checkbox"> Show closed and expired sessions</label><label><input id="show-empty" type="checkbox"> Show empty sessions</label><label>Layout <select id="layout-filter"><option value="columns">Columns</option><option value="rows">Rows</option></select></label><label>Recent window <input id="recent-window" type="number" min="1" step="1" aria-label="Recent window in seconds"> sec</label><button id="apply-window" type="button">Apply</button><span class="muted" id="visible-summary"></span></section>
<section id="projects"></section></main>
<script>
const endpoint=new URL(__SNAPSHOT_PATH__,window.location.href);
const initialRecent=new URLSearchParams(window.location.search).get('recent-seconds'); if(initialRecent) endpoint.searchParams.set('recent-seconds',initialRecent);
const stateFilter=document.getElementById('state-filter'); const showClosed=document.getElementById('show-closed'); const showEmpty=document.getElementById('show-empty'); const layoutFilter=document.getElementById('layout-filter'); const recentWindow=document.getElementById('recent-window'); let latest=null; let refreshGeneration=0; let refreshInFlight=false;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const stamp=x=>{if(x===undefined||x===null||x===''||(typeof x==='number'&&!Number.isFinite(x)))return ''; const d=new Date(x); return Number.isFinite(d.getTime())?d.toLocaleString():''}; const isClosed=s=>['closed','expired'].includes(s?.state); const timestamp=x=>{const value=Date.parse(x||''); return Number.isFinite(value)?value:-Infinity}; const recent=x=>Math.max(...['updated-at','last-activity-at','closed-at','created-at'].map(key=>timestamp(x?.[key])));
const byNewest=(a,b)=>recent(b)-recent(a); const stateClass=s=>'state-'+String(s||'').replaceAll('_','-');
const ACTIVE_REQUEST_STATES=new Set(['queued','dispatching','running']);
function badge(state) { return `<span class="badge ${stateClass(state)}">${esc(state||'unknown')}</span>`; }
function queueSummary(queues) { const entries=Object.entries(queues||{}); if(!entries.length) return 'no queue data'; return entries.map(([profile,depth])=>{const d=depth||{}; const parts=[]; if(d.pending) parts.push(`${d.pending} pending`); if(d.active_running) parts.push(`${d.active_running} running`); if(d.idle) parts.push(`${d.idle} idle`); return `${profile}: ${parts.join(', ')||'idle'}`}).join(' · '); }
function watchdogFlag(r) { const ws=r['watchdog-state']; if(!ws||ws==='not-started') return ''; const title=r['watchdog-reason']?` title="${esc(r['watchdog-reason'])}"`:''; if(['completed','failed','cancelled','rejected','interrupted'].includes(r.state)) return `<span class="flag stale"${title}>stale monitoring marker</span>`; if(ws==='intervention') return `<span class="flag alert"${title}>needs activity proof</span>`; if(ws==='active') return `<span class="flag progress"${title}>watching</span>`; return `<span class="flag"${title}>monitoring: ${esc(ws)}</span>`; }
function sideEffectFlag(r) { const side=r.diagnostics?.['side-effect-state']; if(!['completed','failed','cancelled','rejected','interrupted'].includes(r.state)||side!=='may-have-started') return ''; return `<span class="flag warn" title="The provider may have received this turn; verify the provider session before retrying.">turn uncertain</span>`; }
function activityLabel(r) { const phase=r['activity-type']||''; const fallback=phase||(r.state==='queued'?'waiting':(ACTIVE_REQUEST_STATES.has(r.state)?r.state:'')); const seq=r['activity-sequence']; return `${esc(fallback)}${seq!==undefined?` <span class="muted">#${esc(seq)}</span>`:''}`; }
const focusEndpoint=__FOCUS_PATH__; const purgeEndpoint=__PURGE_PATH__; const focusToken=__FOCUS_TOKEN__;
const focusIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>';
const purgeIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';
function chatLink(r) { if(!r['focus-tab-available']) return ''; return ` <button type="button" class="action-button icon-button icon-action focus-chat" data-request-id="${esc(r['request-id'])}" aria-label="Open or focus GPT tab" title="Open the retained GPT tab, or focus it if already open">${focusIcon}</button>`; }
function setFeedback(button, text) { button.classList.add('feedback'); button.title=text; button.setAttribute('aria-label',text); setTimeout(()=>button.classList.remove('feedback'),1800); }
async function focusChat(button) { const id=button.dataset.requestId; button.disabled=true; try { const response=await fetch(focusEndpoint,{method:'POST',headers:{'Content-Type':'application/json','X-AudiaGentic-Dashboard-Token':focusToken},body:JSON.stringify({'request-id':id})}); const body=await response.json(); const result=body.result||{}; setFeedback(button,result.reason==='conversation-tab-opened'?'GPT tab opened':(result.outcome==='focused'?'GPT tab focused':(result.reason||result.outcome||'GPT tab unavailable'))); } catch(error) { setFeedback(button,'GPT tab unavailable'); } finally { setTimeout(()=>{button.disabled=false;},1200); } }
async function purgeSession(button) { const id=button.dataset.sessionId; if(!window.confirm('Purge this session and all gateway request data? This cannot be undone.')) return; button.disabled=true; try { const response=await fetch(purgeEndpoint,{method:'POST',headers:{'Content-Type':'application/json','X-AudiaGentic-Dashboard-Token':focusToken},body:JSON.stringify({'session-id':id})}); const body=await response.json(); const result=body.result||{}; setFeedback(button,result.outcome==='purged'?'Session purged':(result.reason||result.outcome||'Purge unavailable')); if(result.outcome==='purged') setTimeout(refresh,400); } catch(error) { setFeedback(button,'Purge unavailable'); } finally { setTimeout(()=>{button.disabled=false;},1200); } }
function bindFocusButtons() { document.querySelectorAll('.focus-chat').forEach(button=>button.addEventListener('click',()=>focusChat(button))); document.querySelectorAll('.purge-session').forEach(button=>button.addEventListener('click',()=>purgeSession(button))); }
function requestHeader(includeExecution=true) { const labels=includeExecution?['Request','State','Activity','Profile / provider','Updated / error']:['Request','State','Activity','Updated','Error']; return `<div class="request-header" role="row">${labels.map(label=>`<div role="columnheader">${label}</div>`).join('')}</div>`; }
function requestRows(rows, includeExecution=true) { const ordered=rows.slice().sort(byNewest); if(!ordered.length)return `<div class="muted">No matching requests</div>`; return requestHeader(includeExecution)+ordered.map(r=>{const d=r.diagnostics||{}; const execution=includeExecution?`${esc(r['execution-profile-id']||'')} / ${esc(r['resolved-provider-id']||'')}`:''; const error=esc(d.classification||r.error?.code||'')+' '+esc(d['recovery']?.disposition||r.error?.message||''); return `<div class="request-row"><div class="request-identity"><code class="request-id">${esc(r['request-id'])}</code>${chatLink(r)}</div><div>${badge(r.state)}${r['provider-turn-pending']?' <span class="live">unresolved</span>':''}${sideEffectFlag(r)}${watchdogFlag(r)}</div><div class="request-meta">${activityLabel(r)||'<span class="muted">none</span>'}</div>${includeExecution?`<div class="request-meta">${execution}</div>`:'<div class="request-meta">'+stamp(recent(r))+'</div>'}<div class="request-error">${includeExecution?stamp(recent(r))+' · ':''}${error||'<span class="muted">none</span>'}</div></div>`}).join(''); }
function matchesState(session, rows) { const wanted=stateFilter.value; return wanted==='all'||session.state===wanted||rows.some(r=>r.state===wanted); }
function matchesRequest(row) { return stateFilter.value==='all'||row.state===stateFilter.value; }
function sessionCard(session, rows, empty=false, allRows=rows) { const purgeable=!allRows.some(r=>ACTIVE_REQUEST_STATES.has(r.state))&&!session['turn-active']&&!(session['pending-turns']>0); const purge=purgeable?`<button type="button" class="action-button icon-button purge-session" data-session-id="${esc(session['session-id'])}" aria-label="Purge session" title="Permanently remove this session and all gateway data">${purgeIcon}</button>`:''; return `<details class="session ${stateClass(session.state)}" open><summary><div class="session-head"><div><h3><code>${esc(session['session-id'])}</code> ${session.live?'<span class="live">live</span>':''}</h3><span class="muted">${esc(session['execution-profile-id']||'')}${session['provider-id']?' · '+esc(session['provider-id']):''}${session['model-id']?' / '+esc(session['model-id']):''}</span></div><div>${badge(session.state)} ${session['turn-active']?'<span class="live">turn active</span>':''}</div><div class="session-actions"><span class="muted">${session['turn-count']||0} turns · ${session['pending-turns']||0} pending · ${stamp(recent(session))}</span>${purge}</div></div></summary><div class="session-body"><div class="request-grid">${empty?'<div class="muted">No matching requests</div>':requestRows(rows,false)}</div></div></details>`; }
function requestGroup(state) { if(ACTIVE_REQUEST_STATES.has(state)) return 'active'; if(['failed','rejected','interrupted','timed-out','expired','abandoned'].includes(state)) return 'failed'; return 'completed'; }
function groupNewest(group) { const rows=group[1]||[]; return rows.length?Math.max(...rows.map(recent)):recent(group[0]); }
function projectView(project) {
  const grouped=new Map(); const requests=(project.requests||[]);
  requests.forEach(r=>{const id=r['session-id']; if(id){const existing=grouped.get(id)||[]; existing.push(r); grouped.set(id,existing)}});
  const knownSessionIds=new Set((project.sessions||[]).map(s=>s['session-id'])); const wanted=stateFilter.value;
  const sessionGroups=(project.sessions||[]).map(s=>{const allRows=grouped.get(s['session-id'])||[]; const sessionMatches=wanted==='all'||s.state===wanted; const rows=sessionMatches?allRows:allRows.filter(r=>r.state===wanted); return {session:s,allRows,rows}}).filter(group=>{const s=group.session; const hasRows=group.rows.length>0; return (showClosed.checked||!isClosed(s)||hasRows)&&(showEmpty.checked||hasRows)&& (wanted==='all'||s.state===wanted||hasRows)});
  const sections={active:[],completed:[],failed:[]}; const emptySessions=[];
  sessionGroups.forEach(group=>{const bySection={active:[],completed:[],failed:[]}; group.rows.forEach(r=>bySection[requestGroup(r.state)].push(r)); let placed=false; Object.entries(bySection).forEach(([name,rows])=>{if(rows.length){sections[name].push([group.session,rows,group.allRows]); placed=true}}); if(!placed&&showEmpty.checked) emptySessions.push(group.session);});
  const unbound=requests.filter(r=>(!r['session-id']||!knownSessionIds.has(r['session-id']))&&matchesRequest(r)); unbound.forEach(r=>sections[requestGroup(r.state)].push([null,[r],[]]));
  Object.values(sections).forEach(groups=>groups.sort((a,b)=>groupNewest(b)-groupNewest(a))); if(!sections.active.length&&!sections.completed.length&&!sections.failed.length&&!emptySessions.length)return '';
  const tally={}; requests.forEach(r=>{tally[r.state]=(tally[r.state]||0)+1}); const pills=Object.entries(tally).map(([state,n])=>`<span class="pill ${stateClass(state)}">${n} ${esc(state)}</span>`).join('');
  const section=(title,groups)=>{if(!groups.length)return ''; return `<section class="work-section"><h3>${title}</h3><div class="sessions">${groups.map(([s,rows,allRows])=>s?sessionCard(s,rows,false,allRows):`<div class="orphan"><div class="request-grid">${requestRows(rows)}</div></div>`).join('')}</div></section>`};
  const empty=emptySessions.length?`<section class="work-section"><h3>Empty sessions</h3><div class="sessions">${emptySessions.sort(byNewest).map(s=>sessionCard(s,[],true,[])).join('')}</div></section>`:'';
  return `<section class="project"><div class="project-head"><div><div class="project-name"><span class="icn">▣</span>${esc(project.name)}</div><div class="queue">${esc(queueSummary(project.queues))}</div></div><div class="pills">${pills}</div></div>${section('Active',sections.active)}${section('Completed',sections.completed)}${section('Failed',sections.failed)}${empty}</section>`;
}
function populateStates(snapshot) { const prior=stateFilter.value; const states=new Set(); (snapshot.projects||[]).forEach(p=>{(p.sessions||[]).forEach(s=>states.add(s.state));(p.requests||[]).forEach(r=>states.add(r.state))}); stateFilter.innerHTML='<option value="all">All states</option>'+[...states].filter(Boolean).sort().map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join(''); stateFilter.value=[...stateFilter.options].some(o=>o.value===prior)?prior:'all'; }
function draw(snapshot) {
  latest=snapshot; populateStates(snapshot);
  const chosenLayout=localStorage.getItem('gateway-dashboard-layout')||'columns'; layoutFilter.value=chosenLayout;
  const dashboard=snapshot.dashboard||{}; if(document.activeElement!==recentWindow) recentWindow.value=dashboard['recent-window-seconds']??'';
  document.getElementById('updated').textContent='Updated '+new Date().toLocaleTimeString();
  const diag=snapshot['provider-diagnostics']||{}; const errorCount=(diag['provider-load-errors']||[]).length;
  document.getElementById('health').classList.toggle('stale', errorCount>0);
  const sessionCount=(snapshot.projects||[]).reduce((n,p)=>n+(p.sessions||[]).length,0);
  const runningCount=(snapshot.counts||{}).running||0;
  const failedCount=((snapshot.counts||{}).failed||0)+((snapshot.counts||{}).rejected||0)+((snapshot.counts||{}).interrupted||0);
  document.getElementById('counts').innerHTML=[
    `<div class="card"><div class="label">Projects</div><div class="value info">${(snapshot.projects||[]).length}</div></div>`,
    `<div class="card"><div class="label">Sessions</div><div class="value info">${sessionCount}</div></div>`,
    `<div class="card"><div class="label">Running</div><div class="value warn">${runningCount}</div></div>`,
    `<div class="card"><div class="label">Failed</div><div class="value bad">${failedCount}</div></div>`,
    `<div class="card"><div class="label">Providers loaded</div><div class="value good">${diag['providers-loaded']??0}</div></div>`,
    `<div class="card"><div class="label">Provider errors</div><div class="value ${errorCount?'bad':'good'}">${errorCount}</div></div>`,
  ].join('');
  const projects=(snapshot.projects||[]).map(projectView).join('');
  const projectsElement=document.getElementById('projects'); projectsElement.className='layout-'+chosenLayout; projectsElement.innerHTML=projects||'<div class="empty">No sessions match these filters.</div>';
  bindFocusButtons();
  const visible=document.querySelectorAll('#projects .session').length;
  document.getElementById('visible-summary').textContent=`${visible} sessions visible · newest first · ${dashboard['recent-window-seconds']??''} sec window`;
}
async function refresh(){if(refreshInFlight)return; const generation=++refreshGeneration; refreshInFlight=true; try{const response=await fetch(endpoint,{cache:'no-store'}); const snapshot=await response.json(); if(generation===refreshGeneration) draw(snapshot);}catch(error){if(generation===refreshGeneration){document.getElementById('health').classList.add('stale');document.getElementById('updated').textContent='Dashboard refresh failed: '+error}}finally{refreshInFlight=false;}}
function applyWindow(){const value=recentWindow.value.trim(); if(value){const parsed=Number.parseInt(value,10); if(!Number.isInteger(parsed)||parsed<1)return; endpoint.searchParams.set('recent-seconds',String(parsed));}else endpoint.searchParams.delete('recent-seconds'); const pageUrl=new URL(window.location.href); if(endpoint.searchParams.has('recent-seconds')) pageUrl.searchParams.set('recent-seconds',endpoint.searchParams.get('recent-seconds')); else pageUrl.searchParams.delete('recent-seconds'); window.history.replaceState(null,'',pageUrl.pathname+(pageUrl.search?`?${pageUrl.searchParams}`:'')+pageUrl.hash); refresh();}
stateFilter.addEventListener('change',()=>latest&&draw(latest)); showClosed.addEventListener('change',()=>latest&&draw(latest)); showEmpty.addEventListener('change',()=>latest&&draw(latest)); layoutFilter.addEventListener('change',()=>{localStorage.setItem('gateway-dashboard-layout',layoutFilter.value); latest&&draw(latest)}); document.getElementById('apply-window').addEventListener('click',applyWindow); refresh(); setInterval(refresh,3000);
</script></main>""".replace("__SNAPSHOT_PATH__", source).replace("__FOCUS_PATH__", focus_source).replace("__PURGE_PATH__", purge_source).replace("__FOCUS_TOKEN__", token_source)
    return html.encode("utf-8")


__all__ = ["dashboard_snapshot", "render_dashboard_html"]

