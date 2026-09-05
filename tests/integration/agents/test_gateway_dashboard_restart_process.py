"""Real restart on an isolated port/store; never stop the operator's gateway."""
import json
import os
import subprocess
import sys
import time
from urllib.request import Request, urlopen

from audiagentic.components.agents.gateway.service.host import GATEWAY_SERVICE_KEY
from audiagentic.foundation.system.managed_process import observe_process, signal_owned_process
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.process import choose_free_port


def test_dashboard_restart_launches_new_owner_on_same_port(tmp_path):
    port = choose_free_port("127.0.0.1")
    root = tmp_path / "services"
    token = tmp_path / "auth.token"
    store = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=root)
    env = os.environ.copy()
    env.pop("AUDIAGENTIC_SERVICE_OWNER_EPOCH", None)
    with (tmp_path / "startup.log").open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "audiagentic.components.agents.gateway.service.process", "--port", str(port), "--service-root", str(root), "--token-file", str(token)],
            env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        def running_epoch(previous=None):
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                try:
                    request = Request(f"http://127.0.0.1:{port}/v1/health", headers={"Authorization": "Bearer " + token.read_text().strip()})
                    with urlopen(request, timeout=1) as response:
                        health = json.load(response)["result"]
                    if health["state"] == "running" and health["owner-epoch"] != previous:
                        return health["owner-epoch"]
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(0.1)
            raise AssertionError("isolated gateway did not reach readiness")
        try:
            before = running_epoch()
            dashboard_token = (store.root / "dashboard-action.token").read_text().strip()
            request = Request(f"http://127.0.0.1:{port}/dashboard/restart", data=b"{}", headers={"X-AudiaGentic-Dashboard-Token": dashboard_token})
            with urlopen(request, timeout=5) as response:
                assert response.status == 202
            after = running_epoch(before)
            assert after != before
            assert store.read().process.pid != process.pid
            process.wait(timeout=10)
            assert process.returncode == 0
        finally:
            # Only signal this test-owned process, with current ownership proof.
            evidence = store.read().process
            if evidence is not None:
                observed = observe_process(evidence)
                if observed is not None:
                    signal_owned_process(evidence, observed, force=True)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
