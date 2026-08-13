"""Dedicated GPT-auto operator dashboard (temporary relocation seam)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

_DASHBOARD_HTML = """<!doctype html><html><head><meta charset='utf-8'><title>GPT-auto dashboard</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#131b31;--panel2:#182441;--line:#293858;--text:#e8eefb;--muted:#91a0bd;--cyan:#45d6d6;--green:#5ee39a;--amber:#f7c873;--red:#ff7885;--shadow:0 18px 45px #05091480}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 85% 0,#1c3860 0,#0b1020 42%);color:var(--text);font:14px/1.45 Inter,Segoe UI,system-ui,sans-serif;min-width:720px}
.shell{max-width:1320px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:24px}.eyebrow{color:var(--cyan);font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase}.title{font-size:30px;font-weight:750;letter-spacing:-.03em;margin:4px 0}.sub{color:var(--muted)}.pulse{display:flex;gap:9px;align-items:center;color:var(--green);font-weight:650}.dot{width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 16px var(--green)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}.card{background:linear-gradient(145deg,#182441e8,#10182ce8);border:1px solid var(--line);border-radius:15px;padding:18px;box-shadow:var(--shadow)}.label{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.1em}.metric{font-size:25px;font-weight:750;margin-top:5px}.metric.good{color:var(--green)}.metric.warn{color:var(--amber)}
.section{display:flex;justify-content:space-between;align-items:center;margin:25px 0 11px}.section h2{font-size:16px;margin:0}.count{background:#263657;color:var(--cyan);border-radius:99px;padding:3px 9px;font-size:12px}.jobs{display:grid;gap:10px}.job{display:grid;grid-template-columns:10px 1fr auto;gap:13px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}.bar{width:8px;height:38px;border-radius:5px;background:var(--cyan)}.bar.complete{background:var(--green)}.bar.busy{background:var(--amber);box-shadow:0 0 13px #f7c87388}.bar.failed{background:var(--red)}.jobtitle{font-weight:700}.meta{color:var(--muted);font-size:12px;margin-top:3px}.badge{border:1px solid var(--line);border-radius:99px;padding:5px 10px;color:var(--cyan);font-size:12px}.empty{color:var(--muted);padding:24px;text-align:center;border:1px dashed var(--line);border-radius:12px}.footer{color:var(--muted);font-size:11px;margin-top:20px}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}}
</style></head><body><main class='shell'><header class='top'><div><div class='eyebrow'>AUDiaGentic · shared browser runtime</div><div class='title'>GPT-auto operations</div><div class='sub'>Projects, sessions, queue and provider activity</div></div><div class='pulse'><span class='dot'></span><span id='health'>Starting</span></div></header>
<section class='grid'><div class='card'><div class='label'>Runtime</div><div class='metric good' id='runtime'>—</div></div><div class='card'><div class='label'>Active sessions</div><div class='metric' id='sessions'>0</div></div><div class='card'><div class='label'>Running jobs</div><div class='metric' id='running'>0</div></div><div class='card'><div class='label'>Queued jobs</div><div class='metric warn' id='queued'>0</div></div></section>
<div class='section'><h2>Jobs & sessions</h2><span class='count' id='count'>0 total</span></div><section class='jobs' id='jobs'><div class='empty'>Waiting for gateway activity…</div></section><div class='footer'>Last updated <span id='updated'>—</span> · Tab creation is serialized; active sessions run independently.</div></main>
<script>window.renderDashboard=function(v){const ss=v.sessions||[],q=v.queue||{};const state=String(v.runtime||'unknown');document.title='GPT-auto · '+state+' · '+ss.length+' sessions';document.getElementById('runtime').textContent=state;document.getElementById('health').textContent=state==='available'?'Operational':state;document.getElementById('sessions').textContent=ss.length;document.getElementById('running').textContent=q.running??ss.filter(s=>['busy','generating','running'].includes(s.state)).length;document.getElementById('queued').textContent=q.queued??0;document.getElementById('count').textContent=ss.length+' total';document.getElementById('updated').textContent=new Date().toLocaleTimeString();const root=document.getElementById('jobs');root.innerHTML=ss.length?ss.map(s=>{const st=String(s.state||'unknown');const cls=st.includes('fail')?'failed':st==='ready'||st==='closed'?'complete':'busy';return `<article class='job'><i class='bar ${cls}'></i><div><div class='jobtitle'>${esc(s.project||'GPT-auto project')}</div><div class='meta'>${esc(s.session||'—')} · page ${esc(s.page||'—')} · turn ${esc(s.turn||'idle')}</div></div><span class='badge'>${esc(st)}</span></article>`}).join(''):'<div class="empty">No active GPT-auto sessions</div>'};function esc(x){return String(x).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}</script></body></html>"""

STATUS_PAGE_URL = "data:text/html;charset=utf-8," + quote(_DASHBOARD_HTML, safe="")


async def render_status_page(bridge: Any, page_handle: str, payload: dict[str, Any]) -> None:
    await bridge.evaluate(
        page_handle,
        """(value) => { if (typeof window.renderDashboard !== 'function') return false; window.renderDashboard(value); return true; }""",
        payload,
    )
