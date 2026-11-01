"""SH30-A: dashboard close/archive/operation-status routes and their application methods."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from audiagentic.components.agents.gateway.service import known_projects
from audiagentic.components.agents.gateway.service.application import GatewayServiceApplication
from audiagentic.components.agents.gateway.service.dashboard_images import project_image_id
from audiagentic.components.agents.gateway.service.http_transport import GatewayHTTPServer
from audiagentic.foundation.contracts.errors import AudiaGenticError

TOKEN = {"X-AudiaGentic-Dashboard-Token": "test-token"}


def _application(tmp_path, roots):
    app = object.__new__(GatewayServiceApplication)
    app._application = Mock()
    app._operations = Mock()
    app._operations.create_operation.side_effect = lambda command: {"operation-id": command.operation_id, "state": "accepted"}
    app._service_store = SimpleNamespace(root=tmp_path / "service")
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
    registry = SimpleNamespace(projects=tuple(SimpleNamespace(project_root=root) for root in roots))
    return app, registry


@pytest.fixture
def known(monkeypatch, tmp_path):
    roots = [tmp_path / "alpha", tmp_path / "beta"]
    app, registry = _application(tmp_path, roots)
    monkeypatch.setattr(known_projects, "load_known_projects", lambda _path: registry)
    return app, roots


def test_close_uses_the_named_project_and_the_public_session_api(known):
    app, (alpha, beta) = known
    app._application.close_execution_session.return_value = {"state": "closed"}
    assert app.close_dashboard_session(project_image_id(beta), "ses_1") == {"state": "closed"}
    app._application.close_execution_session.assert_called_once_with(beta, "ses_1")
    app._application.purge_execution_session.assert_not_called()


def test_archive_creates_the_existing_operation_with_the_resolved_root(known):
    app, (alpha, _beta) = known
    result = app.archive_dashboard_request(project_image_id(alpha), "req_example_000000000001")
    command = app._operations.create_operation.call_args.args[0]
    assert command.kind.value == "archive" and result["state"] == "accepted"
    assert command.scope == {"project-root": str(alpha), "request-ids": ["req_example_000000000001"]}


def test_an_unknown_project_is_refused_and_nothing_is_searched_or_created(known):
    app, _ = known
    for call in (lambda: app.close_dashboard_session("0" * 64, "s"),
                 lambda: app.archive_dashboard_request("not-a-hash", "r")):
        with pytest.raises(AudiaGenticError, match="CON-AGSV-032"):
            call()
    app._operations.create_operation.assert_not_called()
    app._application.close_execution_session.assert_not_called()


def test_a_request_id_slug_is_not_an_authority(known):
    """The request id names a project slug but the supplied project decides where the operation runs."""
    app, (alpha, beta) = known
    app.archive_dashboard_request(project_image_id(beta), "req_example_000000000001")
    assert app._operations.create_operation.call_args.args[0].scope["project-root"] == str(beta)


def test_operation_status_reads_the_operations_authority(known):
    app, _ = known
    app._operations.get_operation.return_value = {"operation-id": "op_1", "state": "running"}
    assert app.dashboard_operation_status("op_1")["state"] == "running"


@pytest.mark.parametrize("action,good,method", [
    ("close-session", {"project-id": "p", "session-id": "s"}, "close_dashboard_session"),
    ("archive-request", {"project-id": "p", "request-id": "r"}, "archive_dashboard_request"),
    ("operation-status", {"operation-id": "op_1"}, "dashboard_operation_status"),
])
def test_routes_need_the_token_an_exact_body_and_call_the_application(action, good, method):
    application = SimpleNamespace(dashboard_action_token="test-token")
    for name in ("close_dashboard_session", "archive_dashboard_request", "dashboard_operation_status"):
        setattr(application, name, Mock(return_value={"state": "accepted"}))
    server = GatewayHTTPServer(("127.0.0.1", 0), application, "secret", dashboard_path="/operator")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/operator/{action}"
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(Request(endpoint, data=b"", headers={}), timeout=2)
        assert error.value.code == 401
        for body in ({**good, "extra": 1}, {k: v for k, v in list(good.items())[:-1]}):
            with pytest.raises(HTTPError) as error:
                urlopen(Request(endpoint, data=json.dumps(body).encode(), headers=TOKEN), timeout=2)
            assert error.value.code == 400
        getattr(application, method).assert_not_called()
        with urlopen(Request(endpoint, data=json.dumps(good).encode(), headers=TOKEN), timeout=2) as response:
            assert response.status == (200 if action in ("close-session", "operation-status") else 202)
            assert json.load(response)["ok"]
        getattr(application, method).assert_called_once_with(*(good[key] for key in sorted(good)))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


# --- SH30-B: dashboard controls (rendered markup and the real action functions run under node) ---

import shutil
import subprocess

from audiagentic.components.agents.gateway.service.dashboard import render_dashboard_html


def _action_source() -> str:
    html = render_dashboard_html("/dashboard/snapshot", focus_token="tok").decode()
    start, end = html.index(" const archiveIcon="), html.index(" const PROVIDER_CAPTURE_STATES")
    return html[start:end]


def test_archive_and_close_controls_are_state_gated_and_carry_the_project():
    html = render_dashboard_html("/dashboard/snapshot").decode()
    assert "ARCHIVABLE_REQUEST_STATES.has(r.state)&&r['project-id']" in html
    assert "!SESSION_TERMINAL_STATES.has(session.state)&&session['project-id']" in html
    assert 'data-project-id="${esc(r[\'project-id\'])}"' in html and 'aria-label="Archive request"' in html
    assert 'aria-label="Close session"' in html
    assert "${completeControl(r)}${cancelControl(r)}${archiveControl(r)}" in html
    assert "${sessionChatControl(session)}${closeControl(session)}${purge}" in html


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the dashboard functions")
def test_the_action_functions_post_poll_and_report_outcomes():
    harness = r"""
const calls = [], log = {feedback: '', refreshed: 0};
const esc = v => String(v), focusEndpoint = '/dashboard/focus', focusToken = 'tok';
const ACTIVE_REQUEST_STATES = new Set(['queued','running']), SESSION_TERMINAL_STATES = new Set(['closed','expired','failed']);
const cancelIcon = '';
const document = {getElementById: () => ({set textContent(v){ log.feedback = v; }, get textContent(){ return log.feedback; }})};
const window = {confirm: () => true};
const refresh = async () => { log.refreshed++; };
let script = [];
const fetch = async (url, init) => { const body = JSON.parse(init.body); calls.push([url, body, init.headers['X-AudiaGentic-Dashboard-Token']]);
  const r = script.shift(); return {ok: r.ok !== false, json: async () => r.body}; };
const realSetTimeout = setTimeout; global.setTimeout = (fn) => realSetTimeout(fn, 0);
__SOURCE__
const button = d => ({disabled: false, dataset: d});
(async () => {
  // gating
  if (archiveControl({state: 'completed', 'request-id': 'r', 'project-id': 'p'}) === '') throw new Error('archive hidden for completed');
  if (archiveControl({state: 'running', 'request-id': 'r', 'project-id': 'p'}) !== '') throw new Error('archive shown for running');
  if (archiveControl({state: 'completed', 'request-id': 'r'}) !== '') throw new Error('archive shown without a project');
  if (closeControl({state: 'closed', 'session-id': 's', 'project-id': 'p'}) !== '') throw new Error('close shown for closed');
  if (closeControl({state: 'active', 'session-id': 's', 'project-id': 'p'}) === '') throw new Error('close hidden for live');
  // archive succeeds after polling
  script = [{body: {result: {'operation-id': 'op_1', state: 'accepted'}}}, {body: {result: {state: 'running'}}}, {body: {result: {state: 'succeeded'}}}];
  const b = button({projectId: 'p', requestId: 'req_1'});
  await archiveRequest(b);
  if (calls[0][0] !== '/dashboard/archive-request' || JSON.stringify(calls[0][1]) !== JSON.stringify({'project-id': 'p', 'request-id': 'req_1'}) || calls[0][2] !== 'tok') throw new Error('archive post wrong ' + JSON.stringify(calls[0]));
  if (calls[1][0] !== '/dashboard/operation-status' || calls[1][1]['operation-id'] !== 'op_1') throw new Error('poll wrong');
  if (!log.feedback.startsWith('Archived req_1') || log.refreshed !== 1 || b.disabled) throw new Error('archive outcome ' + log.feedback);
  // archive refused by the executor
  script = [{body: {result: {'operation-id': 'op_2'}}}, {body: {result: {state: 'failed', error: {code: 'VAL-AGM-008', message: 'not terminal'}}}}];
  await archiveRequest(button({projectId: 'p', requestId: 'req_2'}));
  if (!log.feedback.includes('Archive failed: VAL-AGM-008: not terminal')) throw new Error('failure text ' + log.feedback);
  // route refusal shows the registered message, never success
  script = [{ok: false, body: {error: {code: 'CON-AGSV-032', message: 'unknown project'}}}];
  await archiveRequest(button({projectId: 'x', requestId: 'req_3'}));
  if (!log.feedback.includes('CON-AGSV-032')) throw new Error('refusal text ' + log.feedback);
  // close session
  script = [{body: {result: {state: 'closed'}}}];
  await closeSession(button({projectId: 'p', sessionId: 'ses_1'}));
  if (calls.at(-1)[0] !== '/dashboard/close-session' || !log.feedback.startsWith('Session closed')) throw new Error('close ' + log.feedback);
  console.log('ok');
})().catch(e => { console.error(e.message); process.exit(1); });
"""
    result = subprocess.run(["node", "-e", harness.replace("__SOURCE__", _action_source())],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr


def test_snapshot_rows_carry_the_project_id_the_buttons_post(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import store
    from audiagentic.components.agents.gateway.service.dashboard import dashboard_snapshot
    from audiagentic.components.agents.gateway.service.known_projects import record_known_project

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    project = tmp_path / "alpha"
    (project / ".git").mkdir(parents=True)
    service_root = tmp_path / "service"
    service_root.mkdir()
    record_known_project(service_root / "known-projects.json", project_root=project)
    record = store.build_record(execution_profile_id="default", prompt_body="x")
    store.write_record(project, record)
    store.transition_record(project, record["request-id"], "running")
    store.transition_record(project, record["request-id"], "completed")
    snapshot = dashboard_snapshot(service_root)
    (entry,) = snapshot["projects"]
    expected = project_image_id(project)
    assert entry["project-id"] == expected
    assert [row["project-id"] for row in entry["requests"]] == [expected]
    assert [row["project-id"] for row in snapshot["requests"]] == [expected]
