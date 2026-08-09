"""Real CLI-installed providers, real gateway, real local rig — happy path
plus negative coverage.

Unlike the crash-matrix suite (which uses local-openai, has no CLI to
install, and focuses on process-crash recovery), this suite's whole point is
proving the real npm-CLI-install + real harness runtime install + real
gateway dispatch chain works end to end, through the ACTUAL provider CLI
binary, not a fake.

Which provider(s) that covers is discovered DYNAMICALLY, not hardcoded — see
gateway_docker_harness.gateway_rig_compatible_npm_provider_ids(), which
queries AUDiaGentic's own provider descriptor registry (npm-installable
AND declares the "model-projection" automation capability, the same real
signal providers_api.apply_model_sources uses to decide who gets a custom
model-source entry) rather than a fixed provider_id string. Today that
resolves to ["opencode"]; if another npm provider gains model-projection
support, this suite covers it automatically with no code change here.

Each provider's CLI is installed by this test itself, through the same
install_provider_cli path tests/integration/providers/harness.py uses for
its own clean-room recipe tests (see gateway_docker_harness.install_provider)
— never assumed to already be present on the container's PATH.

Provisioning goes through gateway_docker_harness.py for the execution-profile and
provider-CLI-install pieces. The harness runtime config
(.audiagentic/config/harness/ag.yaml) and the rig HTTP handler stay local to
this file: the harness config format is genuine project-authored config (no
creation API exists for it, same status as gateway-profiles.yaml), and this
suite's rig needs SSE streaming support that the crash-matrix suite's
HoldableRigHandler doesn't — a different real requirement, not a shortcut.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from tests.integration.agents.gateway_docker_harness import (
    gateway_rig_compatible_npm_provider_ids,
    install_provider,
    wait_for,
    write_execution_profile,
)
from tests.integration.providers.harness import (
    assert_health_ok,
    assert_install_result_ok,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.opt_in,
    pytest.mark.mutates_host,
    pytest.mark.requires_npm,
    pytest.mark.timeout(180),
]

_VENDOR_ID = "audiagentic"
_MODEL_ID = "audiagentic-rig"
_FULL_MODEL_REF = f"{_VENDOR_ID}/{_MODEL_ID}"
_RIG_PORT = 42001

# Provider-specific config knobs beyond the common install-mode/access-mode
# fields every CLI-based provider shares — kept explicit per provider rather
# than guessed, since each provider's config schema genuinely differs.
_PROVIDER_EXTRA_CONFIG: dict[str, dict] = {
    "opencode": {
        "default-model": _FULL_MODEL_REF,
        "execution-policy": {"output-format": "json"},
    },
}

_DISCOVERED_PROVIDER_IDS = gateway_rig_compatible_npm_provider_ids()


def _skip_if_none_discovered() -> None:
    if not _DISCOVERED_PROVIDER_IDS:
        pytest.skip(
            "no npm-installable, model-projection-capable provider found — "
            "nothing for this suite to dynamically exercise"
        )


class _RigHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []
    # Held before every response is written — lets a test force a request to
    # sit in-flight (e.g. to exercise a real cancel against a real provider
    # process) instead of racing against however fast the fake rig replies.
    hold: threading.Event = threading.Event()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        self.requests.append({"method": "GET", "path": self.path})
        if self.path == "/v1/models":
            self._json({"object": "list", "data": [{"id": _MODEL_ID, "object": "model"}]})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.requests.append({"method": "POST", "path": self.path, "body": body})
        _RigHandler.hold.wait(timeout=30)
        if body.get("stream") is True:
            first = json.dumps(
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": body.get("model", _MODEL_ID),
                    "choices": [
                        {"index": 0, "delta": {"role": "assistant", "content": "GATEWAY_HARNESS_OK"}}
                    ],
                }
            )
            final = json.dumps(
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": body.get("model", _MODEL_ID),
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            )
            data = f"data: {first}\n\ndata: {final}\n\ndata: [DONE]\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._json({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": body.get("model", _MODEL_ID),
            "choices": [{"message": {"role": "assistant", "content": "GATEWAY_HARNESS_OK"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    def _json(self, payload: dict) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@pytest.fixture()
def rig_server():
    _RigHandler.requests = []
    _RigHandler.hold = threading.Event()
    _RigHandler.hold.set()  # default: respond immediately; cancel test clears it
    server = ThreadingHTTPServer(("127.0.0.1", _RIG_PORT), _RigHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        _RigHandler.hold.set()
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _write_harness_config(project_root: Path, provider_id: str) -> None:
    config_root = project_root / ".audiagentic" / "config" / "harness"
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "ag.yaml").write_text(
        yaml.safe_dump(
            {
                "harness": {"type": provider_id},
                "rig": {"port": _RIG_PORT, "model": _MODEL_ID, "provider": _VENDOR_ID},
                "mcp": {"enabled": False},
                "smoke": {"timeout": 60},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _provision_provider_project(tmp_path: Path, provider_id: str, monkeypatch) -> None:
    """Real end-to-end provisioning shared by every test below: harness
    runtime install, real provider CLI install, real model-source wiring."""
    from audiagentic.components.providers import providers_api
    from audiagentic.components.providers.services.config.provider_config import (
        patch_provider_config,
    )
    from audiagentic.launcher import _main

    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_MODE", "in-process")
    monkeypatch.setenv("AUDIAGENTIC_RIG_API_KEY", "dummy")

    write_execution_profile(
        tmp_path,
        profile_id="docker-harness-rig",
        provider_id=provider_id,
        model_id=_FULL_MODEL_REF,
        max_concurrency=1,
    )
    _write_harness_config(tmp_path, provider_id)
    harness_runtime = tmp_path / "harness-runtime"
    assert _main(["--project", str(tmp_path), "bootstrap", "--target", str(harness_runtime)]) == 0

    # Real CLI install, through the same recipe tests/integration/providers/harness.py
    # uses for its own clean-room tests — the fix for the old test's
    # `shutil.which("opencode") is not None` assumption, which only ever
    # passed because the CLI happened to already be on PATH.
    install_result = install_provider(provider_id, project_root=tmp_path)
    assert_install_result_ok(provider_id, install_result)
    assert_health_ok(provider_id, install_result)

    providers_api.model_source_add(
        tmp_path,
        _VENDOR_ID,
        {
            "source-class": "local-endpoint",
            "connector": "openai-compatible",
            "base-url": f"http://127.0.0.1:{_RIG_PORT}/v1",
            "api-key-ref": "env:AUDIAGENTIC_RIG_API_KEY",
            "model-id": _MODEL_ID,
            "display-name": "AUDiaGentic Rig",
            "context-window": 131072,
            "max-output-tokens": 4096,
            "provider-overrides": {"provider-id": _VENDOR_ID},
        },
    )
    inventory = providers_api.list_model_inventory(tmp_path)
    assert (provider_id, "custom-entries") in {
        (harness["provider_id"], harness["mode"])
        for source in inventory["sources"]
        for harness in source["harnesses"]
    }
    apply_result = providers_api.apply_model_sources(tmp_path)
    assert apply_result["ok"] is True, apply_result
    assert any(result["provider_id"] == provider_id for result in apply_result["results"])

    patch_provider_config(
        tmp_path,
        provider_id,
        {
            "access-mode": "cli",
            "install-mode": "external-configured",
            **_PROVIDER_EXTRA_CONFIG.get(provider_id, {}),
        },
    )


@pytest.mark.parametrize("provider_id", _DISCOVERED_PROVIDER_IDS or ["<none-discovered>"])
def test_gateway_runs_real_cli_provider_against_local_rig(
    provider_id: str, tmp_path: Path, monkeypatch, rig_server
) -> None:
    if os.environ.get("AUDIAGENTIC_GATEWAY_OPENCODE_DOCKER") != "1":
        pytest.skip("opt-in Docker gate; set AUDIAGENTIC_GATEWAY_OPENCODE_DOCKER=1")
    _skip_if_none_discovered()

    from audiagentic.components.agents.gateway.client import (
        get_gateway_client,
        reset_gateway_client,
    )

    _provision_provider_project(tmp_path, provider_id, monkeypatch)

    # Opencode-specific direct-CLI smoke check: proves the installed binary
    # itself works against the rig, independent of the gateway. Each
    # provider's real CLI invocation syntax genuinely differs (this is not a
    # generalizable step), so it only runs for the one provider it's written
    # for; the gateway-dispatch assertion below is what's actually generic
    # and runs for every dynamically-discovered provider.
    if provider_id == "opencode":
        opencode = shutil.which("opencode")
        assert opencode is not None, "opencode CLI missing after real install — provisioning did not work"
        config_path = tmp_path / ".opencode" / "opencode.json"
        assert config_path.is_file()
        opencode_config = json.loads(config_path.read_text(encoding="utf-8"))
        opencode_config["provider"][_VENDOR_ID]["options"]["apiKey"] = os.environ["AUDIAGENTIC_RIG_API_KEY"]
        # RV739: OpenCode uses enabled_providers as a whitelist; without it,
        # custom providers are blocked when OPENCODE_CONFIG_CONTENT is used
        # with a global config present. Documented root cause, not silently
        # patched over — see docs/planning/completed/shared-gateway/reviews/SH07/RV739.md.
        if "enabled_providers" not in opencode_config:
            provider_keys = list(opencode_config.get("provider", {}).keys())
            if provider_keys:
                opencode_config["enabled_providers"] = provider_keys
        opencode_config["model"] = _FULL_MODEL_REF
        direct_env = os.environ.copy()
        direct_env["OPENCODE_CONFIG_CONTENT"] = json.dumps(opencode_config)
        direct = subprocess.run(
            [opencode, "run", "--format", "json", "--dir", str(tmp_path), "--model", _FULL_MODEL_REF,
             "Reply exactly GATEWAY_HARNESS_OK"],
            cwd=tmp_path, env=direct_env, capture_output=True, text=True, timeout=60,
        )
        assert direct.returncode == 0, {
            "stdout": direct.stdout, "stderr": direct.stderr, "returncode": direct.returncode,
            "requests": _RigHandler.requests,
        }

    reset_gateway_client()
    client = get_gateway_client()
    try:
        result = client.run_execution_request(
            tmp_path,
            execution_profile_id="docker-harness-rig",
            prompt_body="Reply exactly GATEWAY_HARNESS_OK",
            timeout_seconds=90,
        )
    finally:
        reset_gateway_client()

    print(json.dumps({"provider_id": provider_id, "result": result}, indent=2, sort_keys=True))
    assert result["state"] == "completed", result
    assert result["provider-id"] == provider_id
    assert result["model-id"] == _FULL_MODEL_REF
    assert "GATEWAY_HARNESS_OK" in (result.get("output") or "")


@pytest.mark.parametrize("provider_id", _DISCOVERED_PROVIDER_IDS or ["<none-discovered>"])
def test_gateway_cancel_of_real_provider_request_reaches_terminal_state(
    provider_id: str, tmp_path: Path, monkeypatch, rig_server
) -> None:
    """Negative path: cancelling a request actually running through a real
    provider process must terminate cleanly, not hang or crash the gateway."""
    if os.environ.get("AUDIAGENTIC_GATEWAY_OPENCODE_DOCKER") != "1":
        pytest.skip("opt-in Docker gate; set AUDIAGENTIC_GATEWAY_OPENCODE_DOCKER=1")
    _skip_if_none_discovered()

    from audiagentic.components.agents.gateway.client import (
        get_gateway_client,
        reset_gateway_client,
    )

    _provision_provider_project(tmp_path, provider_id, monkeypatch)
    _RigHandler.hold.clear()  # force the request to sit in-flight until released

    reset_gateway_client()
    client = get_gateway_client()
    try:
        submitted = client.submit_execution_request(
            tmp_path,
            execution_profile_id="docker-harness-rig",
            prompt_body="Reply exactly GATEWAY_HARNESS_OK",
            mode="async",
        )
        request_id = submitted["request-id"]

        wait_for(
            lambda: client.get_execution_request(tmp_path, request_id)["state"] == "running",
            timeout=30, what=f"{provider_id} request to start running",
        )

        client.cancel_execution_request(tmp_path, request_id)
        _RigHandler.hold.set()  # let the held HTTP call return so the process can wind down

        final = client.wait_execution_request(tmp_path, request_id, timeout_seconds=30)
        assert final["state"] in {"cancelled", "failed", "completed"}, final
        assert final["state"] != "running"
    finally:
        reset_gateway_client()


@pytest.mark.parametrize("provider_id", _DISCOVERED_PROVIDER_IDS or ["<none-discovered>"])
def test_gateway_rejects_unresolvable_profile_without_touching_provider(
    provider_id: str, tmp_path: Path, monkeypatch, rig_server
) -> None:
    """Negative path, cheap: an unresolvable execution-profile-id is rejected up
    front — no provider process is spawned for a request that can never
    succeed."""
    if os.environ.get("AUDIAGENTIC_GATEWAY_OPENCODE_DOCKER") != "1":
        pytest.skip("opt-in Docker gate; set AUDIAGENTIC_GATEWAY_OPENCODE_DOCKER=1")
    _skip_if_none_discovered()

    from audiagentic.components.agents.gateway.client import (
        get_gateway_client,
        reset_gateway_client,
    )
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    _provision_provider_project(tmp_path, provider_id, monkeypatch)

    reset_gateway_client()
    client = get_gateway_client()
    try:
        with pytest.raises(AudiaGenticError):
            client.submit_execution_request(
                tmp_path,
                execution_profile_id="profile-that-does-not-exist",
                prompt_body="should never reach the provider",
                mode="async",
            )
        assert _RigHandler.requests == []
    finally:
        reset_gateway_client()
