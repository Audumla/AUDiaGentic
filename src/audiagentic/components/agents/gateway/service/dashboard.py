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
        records = api.list_execution_requests(root)
        sessions = api.list_execution_sessions(root)
        all_session_rows = sorted(
            (_session_row(session, live.get(session["session-id"])) for session in sessions),
            key=_most_recent,
            reverse=True,
        )
        all_request_rows = sorted((_request_row(record) for record in records), key=_most_recent, reverse=True)
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


def _request_row(status: dict[str, Any]) -> dict[str, Any]:
    """Select bounded request facts suitable for an unauthenticated loopback page."""
    visible = (
        "request-id", "execution-profile-id", "resolved-provider-id", "resolved-model-id",
        "state", "session-id", "provider-turn-pending", "created-at", "updated-at",
        "started-at", "finished-at", "last-activity-at", "watchdog-state", "watchdog-reason",
        "latest-transition", "error",
        "diagnostics",
        "output-preview", "output-truncated", "response-artifact",
    )
    return {key: status.get(key) for key in visible if status.get(key) is not None}


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
    """Use the best durable activity timestamp for descending dashboard rows."""
    return str(
        row.get("updated-at")
        or row.get("last-activity-at")
        or row.get("closed-at")
        or row.get("created-at")
        or ""
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


def render_dashboard_html(snapshot_path: str) -> bytes:
    """Return a self-refreshing page.  It has no provider/browser dependency."""
    source = json.dumps(snapshot_path)
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
.queue { font:12px ui-monospace,monospace; color:var(--muted); margin-top:2px }.sessions { display:grid; gap:10px }.session { overflow:hidden; position:relative; border-left:3px solid var(--line) }.session.state-completed { border-left-color:var(--green) }.session.state-failed,.session.state-rejected,.session.state-interrupted { border-left-color:var(--red) }.session.state-queued,.session.state-running,.session.state-dispatching,.session.state-active { border-left-color:var(--amber) }.session summary { cursor:pointer; list-style:none; padding:12px 14px }.session summary::-webkit-details-marker { display:none }.session-head { display:grid; grid-template-columns:minmax(210px,1fr) auto auto; align-items:center }.session-body { border-top:1px solid var(--line); padding:0 14px 12px }
.badge { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 8px; font-size:12px; white-space:nowrap }.state-completed { color:var(--green) }.state-failed,.state-rejected,.state-interrupted { color:var(--red) }.state-queued,.state-running,.state-dispatching,.state-active { color:var(--amber) }.live { color:var(--amber); font-size:12px; font-weight:650 } code { color:var(--teal); font:12px ui-monospace,SFMono-Regular,Consolas,monospace }
.flag { display:inline-block; background:#1c2740; border:1px solid var(--line); color:var(--muted); border-radius:6px; padding:1px 7px; font-size:11px; margin-left:5px }.flag.alert { color:var(--red); border-color:#5a2a30; background:#2a1418; font-weight:650 }.flag.progress { color:var(--amber); border-color:#5a4a24; background:#241c10 }
.watchdog-help { margin:0 0 18px; padding:10px 12px; color:var(--muted); background:#0e1930a8; border:1px solid var(--line); border-radius:10px }.watchdog-help summary { cursor:pointer; color:var(--text); font-weight:650 }.watchdog-help p { margin:8px 0 0 }.watchdog-help ul { display:grid; gap:4px; margin:8px 0 0; padding-left:20px }.flag.stale { color:var(--muted); border-style:dashed }
table { width:100%; border-collapse:collapse } th,td { padding:8px 5px; border-bottom:1px solid #263757; text-align:left; vertical-align:top } th { color:var(--muted); font-weight:600; font-size:12px } tr:last-child td { border-bottom:0 }.error { color:var(--red); font-size:12px }.orphan { padding:14px; margin:14px 0 } select,label { color:var(--text) } select { background:#0b1529; border:1px solid var(--line); border-radius:7px; padding:6px }
.empty { color:var(--muted); padding:24px; text-align:center; border:1px dashed var(--line); border-radius:12px }
input[type=number],button { background:#0b1529; border:1px solid var(--line); border-radius:7px; color:var(--text); padding:6px 8px } input[type=number] { width:100px } button { cursor:pointer } button:hover { border-color:var(--teal) }
@media (max-width:700px) { body { padding:14px }.session-head { grid-template-columns:1fr }.session-body { overflow-x:auto } th:nth-child(3),td:nth-child(3) { display:none } }
</style>
<main><div class="top"><div><div class="eyebrow">AUDiaGentic · shared gateway</div><h1>Agent gateway</h1><div class="muted">Read-only operator view, redacted across all projects on this runtime</div></div><div class="pulse" id="health"><span class="dot"></span><span id="updated">Loading…</span></div></div>
<section class="cards" id="counts"></section>
<section class="toolbar"><label>Request / session state <select id="state-filter"><option value="all">All states</option></select></label><label><input id="show-closed" type="checkbox"> Show closed and expired sessions</label><label><input id="show-empty" type="checkbox"> Show empty sessions</label><label>Recent window <input id="recent-window" type="number" min="1" step="1" aria-label="Recent window in seconds"> sec</label><button id="apply-window" type="button">Apply</button><span class="muted" id="visible-summary"></span></section>
<details class="watchdog-help"><summary>Watchdog monitoring guide</summary><p>The watchdog observes a running attempt's activity lease. It never starts, stops, or fails a request—the request lifecycle state is authoritative.</p><ul><li><b>Not monitoring</b>: no running activity lease.</li><li><b>Watching</b>: the attempt is running and the watchdog is awaiting or has received verified activity.</li><li><b>Needs activity proof</b>: the lease expired; this is a diagnostic only, not a failure.</li><li><b>Stale monitoring marker</b>: legacy watchdog data on a terminal request; it is ignored.</li></ul></details>
<section id="projects"></section></main>
<script>
const endpoint=new URL(__SNAPSHOT_PATH__,window.location.href);
const initialRecent=new URLSearchParams(window.location.search).get('recent-seconds'); if(initialRecent) endpoint.searchParams.set('recent-seconds',initialRecent);
const stateFilter=document.getElementById('state-filter'); const showClosed=document.getElementById('show-closed'); const showEmpty=document.getElementById('show-empty'); const recentWindow=document.getElementById('recent-window'); let latest=null;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const stamp=x=>x?new Date(x).toLocaleString():''; const isClosed=s=>['closed','expired'].includes(s?.state); const recent=x=>x?.['updated-at']||x?.['last-activity-at']||x?.['closed-at']||x?.['created-at']||'';
const byNewest=(a,b)=>recent(b).localeCompare(recent(a)); const stateClass=s=>'state-'+String(s||'').replaceAll('_','-');
function badge(state) { return `<span class="badge ${stateClass(state)}">${esc(state||'unknown')}</span>`; }
function queueSummary(queues) { const entries=Object.entries(queues||{}); if(!entries.length) return 'no queue data'; return entries.map(([profile,depth])=>{const d=depth||{}; const parts=[]; if(d.pending) parts.push(`${d.pending} pending`); if(d.active_running) parts.push(`${d.active_running} running`); if(d.idle) parts.push(`${d.idle} idle`); return `${profile}: ${parts.join(', ')||'idle'}`}).join(' · '); }
function watchdogFlag(r) { const ws=r['watchdog-state']; if(!ws||ws==='not-started') return ''; const title=r['watchdog-reason']?` title="${esc(r['watchdog-reason'])}"`:''; if(['completed','failed','cancelled','rejected','interrupted'].includes(r.state)) return `<span class="flag stale"${title}>stale monitoring marker</span>`; if(ws==='intervention') return `<span class="flag alert"${title}>needs activity proof</span>`; if(ws==='active') return `<span class="flag progress"${title}>watching</span>`; return `<span class="flag"${title}>monitoring: ${esc(ws)}</span>`; }
function requestRows(rows) { return rows.sort(byNewest).map(r=>{const d=r.diagnostics||{}; return `<tr><td><code>${esc(r['request-id'])}</code></td><td>${badge(r.state)}${r['provider-turn-pending']?' <span class="live">unresolved</span>':''}${watchdogFlag(r)}</td><td>${esc(r['execution-profile-id']||'')} / ${esc(r['resolved-provider-id']||'')}</td><td>${stamp(recent(r))}</td><td class="error">${esc(d.classification||r.error?.code||'')} ${esc(d['recovery']?.disposition||r.error?.message||'')}</td></tr>`}).join('')||'<tr><td colspan="5" class="muted">No matching requests</td></tr>'; }
function matchesState(session, rows) { const wanted=stateFilter.value; return wanted==='all'||session.state===wanted||rows.some(r=>r.state===wanted); }
function sessionCard(session, rows) { return `<details class="session ${stateClass(session.state)}" open><summary><div class="session-head"><div><h3><code>${esc(session['session-id'])}</code> ${session.live?'<span class="live">live</span>':''}</h3><span class="muted">${esc(session['execution-profile-id']||'')}${session['provider-id']?' · '+esc(session['provider-id']):''}${session['model-id']?' / '+esc(session['model-id']):''}</span></div><div>${badge(session.state)} ${session['turn-active']?'<span class="live">turn active</span>':''}</div><div class="muted">${session['turn-count']||0} turns · ${session['pending-turns']||0} pending · ${stamp(recent(session))}</div></div></summary><div class="session-body"><table><thead><tr><th>Request</th><th>State</th><th>Profile / provider</th><th>Updated</th><th>Error</th></tr></thead><tbody>${requestRows(rows)}</tbody></table></div></details>`; }
function projectView(project) { const grouped=new Map(); (project.requests||[]).forEach(r=>{const id=r['session-id']; if(id){const existing=grouped.get(id)||[]; existing.push(r); grouped.set(id,existing)}}); const sessions=(project.sessions||[]).filter(s=>{const rows=grouped.get(s['session-id'])||[]; return (showClosed.checked||!isClosed(s))&&(showEmpty.checked||s.live||rows.length>0)&&matchesState(s,rows)}).sort(byNewest); if(!sessions.length)return ''; const tally={}; sessions.forEach(s=>{tally[s.state]=(tally[s.state]||0)+1}); const pills=Object.entries(tally).map(([state,n])=>`<span class="pill ${stateClass(state)}">${n} ${esc(state)}</span>`).join(''); return `<section class="project"><div class="project-head"><div><div class="project-name"><span class="icn">▣</span>${esc(project.name)}</div><div class="queue">${esc(queueSummary(project.queues))}</div></div><div class="pills">${pills}</div></div><div class="sessions">${sessions.map(s=>sessionCard(s,grouped.get(s['session-id'])||[])).join('')}</div></section>`; }
function populateStates(snapshot) { const prior=stateFilter.value; const states=new Set(); (snapshot.projects||[]).forEach(p=>{(p.sessions||[]).forEach(s=>states.add(s.state));(p.requests||[]).forEach(r=>states.add(r.state))}); stateFilter.innerHTML='<option value="all">All states</option>'+[...states].filter(Boolean).sort().map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join(''); stateFilter.value=[...stateFilter.options].some(o=>o.value===prior)?prior:'all'; }
function draw(snapshot) {
  latest=snapshot; populateStates(snapshot);
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
  document.getElementById('projects').innerHTML=projects||'<div class="empty">No sessions match these filters.</div>';
  const visible=document.querySelectorAll('#projects .session').length;
  document.getElementById('visible-summary').textContent=`${visible} sessions visible · newest first · ${dashboard['recent-window-seconds']??''} sec window`;
}
async function refresh(){try{draw(await (await fetch(endpoint)).json())}catch(error){document.getElementById('health').classList.add('stale');document.getElementById('updated').textContent='Dashboard refresh failed: '+error}}
function applyWindow(){const value=recentWindow.value.trim(); if(value){const parsed=Number.parseInt(value,10); if(!Number.isInteger(parsed)||parsed<1)return; endpoint.searchParams.set('recent-seconds',String(parsed));}else endpoint.searchParams.delete('recent-seconds'); refresh();}
stateFilter.addEventListener('change',()=>latest&&draw(latest)); showClosed.addEventListener('change',()=>latest&&draw(latest)); showEmpty.addEventListener('change',()=>latest&&draw(latest)); document.getElementById('apply-window').addEventListener('click',applyWindow); refresh(); setInterval(refresh,1000);
</script></main>""".replace("__SNAPSHOT_PATH__", source)
    return html.encode("utf-8")


__all__ = ["dashboard_snapshot", "render_dashboard_html"]
