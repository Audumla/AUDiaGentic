from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml


pytestmark = [
    pytest.mark.integration,
    pytest.mark.opt_in,
    pytest.mark.requires_npm,
    pytest.mark.timeout(180),
]


class _RigHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        self.requests.append({"method": "GET", "path": self.path})
        if self.path == "/v1/models":
            self._json({"object": "list", "data": [{"id": "audiagentic-rig", "object": "model"}]})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.requests.append({"method": "POST", "path": self.path, "body": body})
        if body.get("stream") is True:
            first = json.dumps(
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": body.get("model", "audiagentic-rig"),
                    "choices": [
                        {"index": 0, "delta": {"role": "assistant", "content": "GATEWAY_OPENCODE_OK"}}
                    ],
                }
            )
            final = json.dumps(
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": body.get("model", "audiagentic-rig"),
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            )
            data = f"data: {first}\n\ndata: {final}\n\ndata: [DONE]\n\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._json({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": body.get("model", "audiagentic-rig"),
            "choices": [{"message": {"role": "assistant", "content": "GATEWAY_OPENCODE_OK"}}],
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
    server = ThreadingHTTPServer(("127.0.0.1", 42001), _RigHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _write_agent_profile(project_root: Path) -> None:
    config_root = project_root / ".audiagentic" / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "agent-profiles.yaml").write_text(
        yaml.safe_dump(
            {
                "contract-version": "v1",
                "profiles": [
                    {
                        "profile_id": "docker-opencode-rig",
                        "provider_id": "opencode",
                        "model_id": "audiagentic/audiagentic-rig",
                        "params": {"retry-count": 0, "max-concurrency": 1},
                        "is_default": True,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_opencode_harness_config(project_root: Path) -> None:
    config_root = project_root / ".audiagentic" / "config" / "harness"
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "ag.yaml").write_text(
        yaml.safe_dump(
            {
                "harness": {"type": "opencode"},
                "rig": {"port": 42001, "model": "audiagentic-rig", "provider": "audiagentic"},
                "mcp": {"enabled": False},
                "smoke": {"timeout": 60},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _collect_opencode_state() -> dict[str, str]:
    roots = [
        Path.home() / ".local" / "share" / "opencode",
        Path.home() / ".config" / "opencode",
    ]
    found: dict[str, str] = {}
    interesting = {"auth.json", "log.txt", "package.json", "package-lock.json"}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.name in interesting:
                try:
                    found[str(path)] = path.read_text(encoding="utf-8", errors="replace")[-4000:]
                except OSError:
                    found[str(path)] = "<unreadable>"
    return found


def test_gateway_runs_opencode_against_local_rig(tmp_path: Path, monkeypatch, rig_server) -> None:
    if os.environ.get("AUDIAGENTIC_GATEWAY_OPENCODE_DOCKER") != "1":
        pytest.skip("opt-in Docker gate; set AUDIAGENTIC_GATEWAY_OPENCODE_DOCKER=1")

    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_MODE", "automatic")
    monkeypatch.setenv("AUDIAGENTIC_RIG_API_KEY", "dummy")

    from audiagentic.components.agents.agents_gateway_client import (
        get_gateway_client,
        reset_gateway_client,
    )
    from audiagentic.components.providers import providers_api
    from audiagentic.components.providers.services.provider_config import (
        patch_provider_config,
        set_provider_enabled,
    )
    from audiagentic.launcher import _main

    _write_agent_profile(tmp_path)
    _write_opencode_harness_config(tmp_path)
    harness_runtime = tmp_path / "harness-runtime"
    assert _main(["--project", str(tmp_path), "install", "--target", str(harness_runtime)]) == 0
    assert (Path.home() / ".local" / "share" / "opencode" / "auth.json").is_file()

    set_provider_enabled(tmp_path, "opencode", enabled=True)
    providers_api.model_source_add(
        tmp_path,
        "audiagentic",
        {
            "source-class": "local-endpoint",
            "connector": "openai-compatible",
            "base-url": "http://127.0.0.1:42001/v1",
            "api-key-ref": "env:AUDIAGENTIC_RIG_API_KEY",
            "model-id": "audiagentic-rig",
            "display-name": "AUDiaGentic Rig",
            "context-window": 131072,
            "max-output-tokens": 4096,
            "provider-overrides": {"provider-id": "audiagentic"},
        },
    )
    inventory = providers_api.list_model_inventory(tmp_path)
    assert ("opencode", "custom-entries") in {
        (harness["provider_id"], harness["mode"])
        for source in inventory["sources"]
        for harness in source["harnesses"]
    }
    apply_result = providers_api.apply_model_sources(tmp_path)
    assert apply_result["ok"] is True, apply_result
    assert any(result["provider_id"] == "opencode" for result in apply_result["results"])
    patch_provider_config(
        tmp_path,
        "opencode",
        {
            "access-mode": "cli",
            "install-mode": "external-configured",
            "default-model": "audiagentic/audiagentic-rig",
            "execution-policy": {"output-format": "json"},
        },
    )
    assert (tmp_path / ".opencode" / "config.json").is_file()
    assert (tmp_path / ".opencode" / "opencode.json").is_file()
    completed = subprocess.run(["opencode", "--version"], capture_output=True, text=True, check=True)
    assert completed.stdout.strip()
    direct = subprocess.run(
        [
            "opencode",
            "run",
            "--format",
            "json",
            "--dir",
            str(tmp_path),
            "--model",
            "audiagentic/audiagentic-rig",
            "Reply exactly GATEWAY_OPENCODE_OK",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(
        json.dumps(
            {
                "direct_stdout": direct.stdout,
                "direct_stderr": direct.stderr,
                "direct_returncode": direct.returncode,
                "project_opencode_config": (tmp_path / ".opencode" / "opencode.json").read_text(encoding="utf-8"),
                "rig_requests": _RigHandler.requests,
                "opencode_state": _collect_opencode_state(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    assert direct.returncode == 0, {
        "stdout": direct.stdout,
        "stderr": direct.stderr,
        "returncode": direct.returncode,
        "config": (tmp_path / ".opencode" / "opencode.json").read_text(encoding="utf-8"),
        "requests": _RigHandler.requests,
    }

    reset_gateway_client()
    client = get_gateway_client()
    result = client.run_llm_request(
        tmp_path,
        agent_profile_id="docker-opencode-rig",
        prompt_body="Reply exactly GATEWAY_OPENCODE_OK",
        timeout_seconds=90,
    )
    reset_gateway_client()

    print(json.dumps(result, indent=2, sort_keys=True))
    assert result["state"] == "completed", result
    assert result["provider-id"] == "opencode"
    assert result["model-id"] == "audiagentic/audiagentic-rig"
    assert "GATEWAY_OPENCODE_OK" in (result.get("output") or "")
