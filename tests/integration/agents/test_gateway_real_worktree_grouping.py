"""Isolated HTTP qualification: real Git worktrees, gpt-auto profile, fake provider transport.

This intentionally tests project resolution, admission, scheduling and the dashboard
without attaching to an authenticated ChatGPT browser or the live gateway.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from tests.helpers.gateway_provider_conformance import patch_gateway_provider_boundaries
from tests.unit.agents.test_agents_gateway_sessions import (
    FakeAgentSessionTransport,
    _build_fake_prepared,
    _build_fake_surface,
)

from audiagentic.components.agents.configuration.management import create_execution_profile
from audiagentic.components.agents.gateway import api, profiles
from audiagentic.components.agents.gateway.remote_client import (
    StandaloneGatewayClient,
    load_auth_token,
)
from audiagentic.components.agents.gateway.service.dashboard_images import (
    project_group_image_id,
    project_image_id,
)
from audiagentic.components.agents.gateway.service.host import GatewayServiceHost
from audiagentic.components.agents.gateway.service.known_projects import record_known_project
from audiagentic.components.agents.gateway.session import sessions as sessions_module
from audiagentic.components.project.project_api import project_id
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state
from audiagentic.foundation.transports.session_surface import SurfaceValidation, ValidationEvidence

pytestmark = pytest.mark.no_parallel


def _run_git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=10)


def _git_worktrees(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main-checkout"
    second = tmp_path / "branch-worktree"
    main.mkdir()
    _run_git("init", "-q", cwd=main)
    (main / ".audiagentic").mkdir()
    (main / ".audiagentic" / "settings.yaml").write_text(
        "schema_version: 1\nproject:\n  id: AUDiaGentic\n  name: AUDiaGentic\n",
        encoding="utf-8",
    )
    _run_git("add", ".audiagentic/settings.yaml", cwd=main)
    _run_git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-qm", "initial tracked project", cwd=main)
    _run_git("worktree", "add", "-q", "-b", "feature/dashboard", str(second), cwd=main)
    assert (second / ".git").is_file()
    assert project_id(main)[0] == project_id(second)[0] == "AUDiaGentic"
    return main, second


@pytest.mark.timeout(60)
def test_gpt_auto_two_real_git_worktrees_share_one_http_dashboard_and_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main, second = _git_worktrees(tmp_path)
    create_execution_profile(main, {
        "profile_id": "gpt-auto",
        "provider_id": "gpt-auto",
        "surface_id": "fake-conformance-surface",
        "instances": ["gpt-auto-model"],
        "is_default": True,
        "params": {"virtual-capacity": 2, "project-capacity": 1, "pending-capacity": 4},
    })
    for root in (main, second):
        set_implementation_state(root, "providers", "gpt-auto", ImplementationState(enabled=True))
    patch_gateway_provider_boundaries(monkeypatch)
    monkeypatch.setattr(
        profiles, "_default_surface_resolver",
        lambda _root, provider, surface: replace(
            _build_fake_surface(provider, surface),
            validation=SurfaceValidation(evidence=ValidationEvidence(
                validated=True, reference=__file__
            )),
        ),
    )

    first_started = threading.Event()
    release_first = threading.Event()

    class HeldGptAuto(FakeAgentSessionTransport):
        async def prompt(self, prompt, sink=None, **kwargs):
            if prompt.body == "GROUPING-HOLD":
                first_started.set()
                self.block_event = release_first
            return await super().prompt(prompt, sink, **kwargs)

    def prepare(*_args, **kwargs):
        transport = HeldGptAuto()
        transport.ag_session_id = kwargs["ag_session_id"]
        return _build_fake_prepared(
            transport, provider_id="gpt-auto", surface_id="fake-conformance-surface"
        )

    runtime = sessions_module.SessionRuntime(
        reap_interval_seconds=60,
        provider_prepare_fn=prepare,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)
    host = None
    thread = None
    client = None
    try:
        host = GatewayServiceHost.create(
            service_root=tmp_path / "isolated-service",
            token_path=tmp_path / "isolated-gateway.token",
            port=0,
        )
        thread = threading.Thread(target=host.serve_forever, daemon=True)
        thread.start()
        for root in (main, second):
            record_known_project(
                host.service_store.root / "known-projects.json", project_root=root
            )
        client = StandaloneGatewayClient(host.endpoint, load_auth_token(host.token_path))

        first = client.submit_execution_request(
            main, execution_profile_id="gpt-auto", prompt_body="GROUPING-HOLD",
            mode="async", new_session=True
        )
        assert first_started.wait(timeout=8), first
        second_request = client.submit_execution_request(
            second, execution_profile_id="gpt-auto", prompt_body="GROUPING-FOLLOW",
            mode="async", new_session=True
        )

        deadline = time.monotonic() + 6
        while True:
            with urlopen(host.endpoint + "/dashboard/snapshot", timeout=3) as response:
                snapshot = json.load(response)
            projects = snapshot["projects"]
            if projects and len(projects[0]["requests"]) == 2:
                break
            assert time.monotonic() < deadline, snapshot
            time.sleep(0.05)

        assert len(projects) == 1, projects
        project = projects[0]
        assert project["name"] == "AUDiaGentic"
        assert project["project-id"] == project_group_image_id("AUDiaGentic")
        assert {r["worktree"] for r in project["requests"]} == {main.name, second.name}
        assert {r["project-id"] for r in project["requests"]} == {
            project_image_id(main), project_image_id(second)
        }
        assert len(project["sessions"]) == 2
        assert project["queues"]["gpt-auto"]["running"] == 1, project["queues"]
        assert project["queues"]["gpt-auto"]["pending"] == 1, project["queues"]
        assert api.get_queue_manager().project_queue_depths(second)["gpt-auto"]["pending"] == 1

        # A real browser loads the real dashboard HTML and fetches its HTTP snapshot.
        if shutil.which("chromium") and importlib.util.find_spec("playwright"):
            from playwright import sync_api

            with sync_api.sync_playwright() as pw:
                browser = pw.chromium.launch(
                    executable_path=shutil.which("chromium"), headless=True,
                    args=["--no-sandbox"],
                )
                try:
                    page = browser.new_page()
                    errors: list[str] = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(host.endpoint + "/dashboard", wait_until="domcontentloaded")
                    page.locator(".project").first.wait_for(timeout=10000)
                    assert page.locator(".project").count() == 1
                    assert page.locator(".session").count() == 2
                    assert "AUDiaGentic" in page.locator(".project-name").first.inner_text()
                    assert not errors, errors
                finally:
                    browser.close()

        release_first.set()
        assert client.wait_execution_request(
            main, first["request-id"], timeout_seconds=10
        )["state"] == "completed"
        assert client.wait_execution_request(
            second, second_request["request-id"], timeout_seconds=10
        )["state"] == "completed"
        with urlopen(host.endpoint + "/dashboard/snapshot", timeout=3) as response:
            completed = json.load(response)
        assert len(completed["projects"]) == 1
        assert len(completed["projects"][0]["requests"]) == 2

        # HTTP actions must retain checkout ownership, not the group ID.
        from audiagentic.components.agents.gateway.session.sessions_store import read_session_record

        app = host.server.application
        assert app._dashboard_project_root(project_image_id(main)) == main
        assert app._dashboard_project_root(project_image_id(second)) == second
        other_state = read_session_record(second, second_request["session-id"])["state"]
        action = Request(
            host.endpoint + "/dashboard/close-session",
            data=json.dumps({"project-id": project_image_id(main),
                             "session-id": first["session-id"]}).encode(),
            headers={"Content-Type": "application/json",
                     "X-AudiaGentic-Dashboard-Token": app.dashboard_action_token},
            method="POST",
        )
        with urlopen(action, timeout=3) as response:
            assert json.load(response)["ok"] is True
        assert read_session_record(main, first["session-id"])["state"] == "closed"
        assert read_session_record(second, second_request["session-id"])["state"] == other_state
    finally:
        release_first.set()
        if client is not None:
            client.close()
        if host is not None:
            host.shutdown()
            if thread is not None:
                thread.join(timeout=5)
                assert not thread.is_alive()
            host.close()
        runtime.shutdown()
