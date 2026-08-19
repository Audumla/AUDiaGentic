"""Provider-neutral operator dashboard (temporary relocation seam).

The page is intentionally a dumb projection: the gateway owns the live
status and pushes snapshots into it.  It must not assume a particular
provider's lifecycle vocabulary.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

_DASHBOARD_HTML = """<!doctype html><html><head><meta charset='utf-8'><title>Agent gateway dashboard</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#131b31;--panel2:#182441;--line:#293858;--text:#e8eefb;--muted:#91a0bd;--cyan:#45d6d6;--green:#5ee39a;--amber:#f7c873;--red:#ff7885;--purple:#b39bff;--shadow:0 18px 45px #05091480}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 85% 0,#1c3860 0,#0b1020 42%);color:var(--text);font:14px/1.45 Inter,Segoe UI,system-ui,sans-serif;min-width:720px}
.shell{max-width:1400px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:24px}.eyebrow{color:var(--cyan);font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase}.title{font-size:30px;font-weight:750;letter-spacing:-.03em;margin:4px 0}.sub{color:var(--muted)}.pulse{display:flex;gap:9px;align-items:center;color:var(--green);font-weight:650}.dot{width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 16px var(--green)}
.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:18px}.card{background:linear-gradient(145deg,#182441e8,#10182ce8);border:1px solid var(--line);border-radius:15px;padding:16px 18px;box-shadow:var(--shadow)}.label{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.1em}.metric{font-size:25px;font-weight:750;margin-top:5px}.metric.good{color:var(--green)}.metric.warn{color:var(--amber)}.metric.bad{color:var(--red)}.metric.info{color:var(--cyan)}
.section{display:flex;justify-content:space-between;align-items:center;margin:25px 0 11px}.section h2{font-size:16px;margin:0}.count{background:#263657;color:var(--cyan);border-radius:99px;padding:3px 9px;font-size:12px}
.projects{display:grid;gap:16px}.proj{background:linear-gradient(180deg,#131b31,#0f1729);border:1px solid var(--line);border-radius:16px;padding:16px 18px;box-shadow:var(--shadow)}
.proj-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.proj-name{font-weight:750;font-size:15px;display:flex;align-items:center;gap:8px}.proj-name .icn{color:var(--purple)}.proj-pills{display:flex;gap:6px;flex-wrap:wrap}.pill{border-radius:99px;padding:3px 9px;font-size:11px;font-weight:650;border:1px solid var(--line);color:var(--muted)}.pill.busy{color:var(--amber);border-color:#5a4a24}.pill.recovering{color:var(--purple);border-color:#463a63}.pill.ready{color:var(--green);border-color:#254a37}.pill.failed{color:var(--red);border-color:#5a2a30}
.jobs{display:grid;gap:8px}.job{display:grid;grid-template-columns:8px 1fr auto;gap:12px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:11px 14px}.bar{align-self:stretch;width:6px;border-radius:5px;background:var(--cyan)}.bar.complete{background:var(--green)}.bar.busy{background:var(--amber);box-shadow:0 0 13px #f7c87388}.bar.failed{background:var(--red)}.bar.recovering{background:var(--purple);box-shadow:0 0 13px #b39bff88}
.jobtitle{font-weight:700;font-size:13px}.meta{color:var(--muted);font-size:11.5px;margin-top:3px}.flags{display:flex;gap:5px;flex-wrap:wrap;margin-top:5px}
.flag{background:#1c2740;border:1px solid var(--line);color:var(--muted);border-radius:6px;padding:1px 6px;font-size:10.5px;transition:background .3s,border-color .3s}
.flag.progress{color:var(--amber);border-color:#5a4a24;background:#241c10}
.flag.evidence{color:var(--cyan);border-color:#1f4a4a;background:#0f2323}
.flag.alert{color:var(--red);border-color:#5a2a30;background:#2a1418;font-weight:650}
.flag.baseline{opacity:.55}
.flag.flash{animation:flash-in 1.6s ease-out}
@keyframes flash-in{0%{box-shadow:0 0 0 4px currentColor;filter:brightness(1.6)}100%{box-shadow:0 0 0 0 transparent;filter:brightness(1)}}
.badge{border:1px solid var(--line);border-radius:99px;padding:5px 10px;color:var(--cyan);font-size:12px;white-space:nowrap;height:fit-content}.badge.busy{color:var(--amber)}.badge.failed{color:var(--red)}.badge.recovering{color:var(--purple)}.badge.ready{color:var(--green)}
.empty{color:var(--muted);padding:24px;text-align:center;border:1px dashed var(--line);border-radius:12px}.footer{color:var(--muted);font-size:11px;margin-top:20px}
@media(max-width:1100px){.grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){.grid{grid-template-columns:repeat(2,1fr)}}
</style></head><body><main class='shell'><header class='top'><div><div class='eyebrow'>AUDiaGentic · shared gateway</div><div class='title'>Agent operations</div><div class='sub'>Per-project sessions, runtime state and live provider activity</div></div><div class='pulse'><span class='dot'></span><span id='health'>Starting</span></div></header>
<section class='grid'>
<div class='card'><div class='label'>Runtime</div><div class='metric good' id='runtime'>—</div></div>
<div class='card'><div class='label'>Sessions</div><div class='metric info' id='sessions'>0</div></div>
<div class='card'><div class='label'>Busy</div><div class='metric warn' id='running'>0</div></div>
<div class='card'><div class='label'>Recovering</div><div class='metric' id='recovering' style='color:var(--purple)'>0</div></div>
<div class='card'><div class='label'>Failed</div><div class='metric bad' id='failed'>0</div></div>
</section>
<div class='section'><h2>Projects</h2><span class='count' id='count'>0 total</span></div>
<section class='projects' id='projects'><div class='empty'>Waiting for gateway activity…</div></section>
<div class='footer'>Last updated <span id='updated'>—</span> · Grouped by AUDiaGentic caller project (this runtime is shared across all projects using this provider on the machine). Gateway-side admission queuing (a request not yet bound to a session) is not visible here.</div></main>
<script>
function statusOf(s){const o=s.observed||{};return String(s.status||s.state||s.lifecycle||o.status||o.state||'unknown')}
function flagsOf(s){const o=s.observed||{};const f=s.flags??o['dom-signals']??o.flags??o.markers??[];return Array.isArray(f)?f:Object.entries(f||{}).filter(([,v])=>v).map(([k])=>k)}
function classFor(s){s=s.toLowerCase();return /fail|error|crash|reject|cancel/.test(s)?'failed':/recover/.test(s)?'recovering':/ready|complete|closed|idle|success/.test(s)?'complete':'busy'}
function badgeClassFor(s){s=s.toLowerCase();return /fail/.test(s)?'failed':/recover/.test(s)?'recovering':/busy|acquiring/.test(s)?'busy':/ready/.test(s)?'ready':''}
function esc(x){return String(x).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}
// Flags are real DOM evidence with very different meanings -- color-code by
// what kind of claim each one makes so a glance distinguishes "the page has
// loaded" (baseline, dimmed) from "something needs attention" (alert, red)
// from "generation in progress" (amber) from "completion evidence" (cyan).
const _FLAG_ALERT = new Set(['rate-limit-dialog', 'error-page', 'error-alert', 'auth-required']);
const _FLAG_PROGRESS = new Set(['stop-control', 'streaming-indicator', 'thinking-indicator', 'busy-indicator']);
const _FLAG_EVIDENCE = new Set(['completion-control', 'message-finalized', 'more-actions-menu', 'canvas-edit-control', 'canvas-open-editor-control']);
const _FLAG_BASELINE = new Set(['url-present', 'composer-present', 'composer-editable', 'composer-ready', 'text-present']);
function flagClass(f){if(_FLAG_ALERT.has(f))return 'alert';if(_FLAG_PROGRESS.has(f))return 'progress';if(_FLAG_EVIDENCE.has(f))return 'evidence';if(_FLAG_BASELINE.has(f))return 'baseline';return ''}
// Every flag is a specific claim about DOM state -- name it plainly so an
// unhighlighted (uncategorized) bubble is no longer a mystery, and every
// bubble's tooltip states its category up front (a bubble with no color
// still gets a real explanation, it's just not one of the four known
// categories above).
const _FLAG_CATEGORY_LABEL = {alert:'Alert', progress:'In progress', evidence:'Completion evidence', baseline:'Baseline', '':'Uncategorized'};
const _FLAG_DESC = {
  'url-present':"Page has a resolvable ChatGPT conversation URL.",
  'composer-present':"The message composer element exists in the DOM.",
  'composer-editable':"The composer currently accepts text input.",
  'composer-ready':"Composer is present, editable, and ready for the next prompt.",
  'text-present':"Assistant response text is present in the DOM.",
  'stop-control':"ChatGPT's 'Stop generating' button is visible -- response is likely still streaming.",
  'streaming-indicator':"The response's streaming animation is active.",
  'thinking-indicator':"The model 'thinking' indicator is visible.",
  'busy-indicator':"aria-busy is set -- ChatGPT itself reports it is still working.",
  'completion-control':"The response's copy button is present -- usually means the turn finished.",
  'message-finalized':"ChatGPT's own DOM marker for 'this is the last rendered message'.",
  'more-actions-menu':"The end-of-turn 'More actions' menu is present, corroborating completion.",
  'canvas-edit-control':"Canvas/writing-block edit control is present (canvas response variant).",
  'canvas-open-editor-control':"Canvas 'Open editor' control is present, pairs with canvas-edit-control.",
  'error-page':"ChatGPT rendered a full error page.",
  'error-alert':"An alert-role error message is showing.",
  'auth-required':"ChatGPT is asking to log in -- this browser session isn't authenticated.",
  'rate-limit-dialog':"ChatGPT's rate-limit dialog is showing (advisory only -- generation can still finish behind it).",
};
function flagTitle(f){const cls=flagClass(f);const label=_FLAG_CATEGORY_LABEL[cls];const desc=_FLAG_DESC[f]||'No description recorded for this signal.';return `${label}: ${desc}`}
// Newly-appeared flags flash once so a state change is actually noticeable
// on a page that repaints every second -- otherwise a bubble silently
// popping into an unchanging-looking list is easy to miss.
const _prevFlags = {};
function sessionRow(s){const st=statusOf(s),cls=classFor(st),flags=flagsOf(s),o=s.observed||{};
  const key=s.session||s.page||'?';
  const prior=_prevFlags[key]||new Set();
  _prevFlags[key]=new Set(flags);
  const genLabel=o.generating===true?'generating':o.generating===false?'idle':null;
  return `<article class='job'><i class='bar ${cls}' title='Session state: ${esc(st)}'></i><div><div class='jobtitle'>${esc(s.session||'session')}</div>`+
    `<div class='meta'>${s.page?`<span title='Browser tab (CDP page handle) backing this session'>Tab: ${esc(s.page)}</span>`:''}${s.turn?` · <span title='Gateway request id for the in-flight turn'>Turn: ${esc(s.turn)}</span>`:''}${genLabel?' · '+genLabel:''}</div>`+
    (flags.length?`<div class='flags'>${flags.map(f=>`<span class='flag ${flagClass(f)}${prior.has(f)?'':' flash'}' title='${esc(flagTitle(f))}'>${esc(f)}</span>`).join('')}</div>`:'')+
    `</div><span class='badge ${badgeClassFor(st)}' title='Session state: ${esc(st)}'>${esc(st)}</span></article>`}
window.renderDashboard=function(v){v=v||{};const ss=[...(v.sessions||[]),...(v.jobs||[])],q=v.queue||{},counts=v.counts||{},providers=v.providers||[];
  let projectGroups=v.projects;
  if(!projectGroups){const byKey={};for(const s of ss){const k=s.project_key||s.project||'unknown';(byKey[k]=byKey[k]||{key:k,name:s.project||k,sessions:[]}).sessions.push(s)}projectGroups=Object.values(byKey)}
  const state=String(v.runtime||v.state||'unknown');
  document.title='Agent gateway · '+state+' · '+ss.length+' sessions';
  document.getElementById('runtime').textContent=state;
  document.getElementById('health').textContent=['available','ready','healthy','operational'].includes(state.toLowerCase())?'Operational':state;
  document.getElementById('sessions').textContent=ss.length;
  document.getElementById('running').textContent=q.running??0;
  document.getElementById('recovering').textContent=q.recovering??counts.recovering??0;
  document.getElementById('failed').textContent=q.failed??counts.failed??0;
  document.getElementById('count').textContent=projectGroups.length+' project'+(projectGroups.length===1?'':'s')+' · '+ss.length+' session'+(ss.length===1?'':'s')+(providers.length?' · '+providers.length+' provider'+(providers.length===1?'':'s'):'');
  document.getElementById('updated').textContent=new Date().toLocaleTimeString();
  const root=document.getElementById('projects');
  if(!projectGroups.length){root.innerHTML='<div class="empty">No active gateway sessions</div>';return}
  root.innerHTML=projectGroups.map(p=>{
    const tally={};for(const s of p.sessions){const st=statusOf(s).toLowerCase();const c=badgeClassFor(st)||'other';tally[c]=(tally[c]||0)+1}
    const pills=Object.entries(tally).map(([k,n])=>`<span class='pill ${k}'>${n} ${esc(k)}</span>`).join('');
    return `<div class='proj'><div class='proj-head'><div class='proj-name'><span class='icn'>▣</span>${esc(p.name)} <span class='count'>${p.sessions.length}</span></div><div class='proj-pills'>${pills}</div></div>`+
      `<div class='jobs'>${p.sessions.map(sessionRow).join('')}</div></div>`
  }).join('')
};
</script></body></html>"""

STATUS_PAGE_URL = "data:text/html;charset=utf-8," + quote(_DASHBOARD_HTML, safe="")


async def render_status_page(bridge: Any, page_handle: str, payload: dict[str, Any]) -> None:
    await bridge.evaluate(
        page_handle,
        """(value) => { if (typeof window.renderDashboard !== 'function') return false; window.renderDashboard(value); return true; }""",
        payload,
    )
