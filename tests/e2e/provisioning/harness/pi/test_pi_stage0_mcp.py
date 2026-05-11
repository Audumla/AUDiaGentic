from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]


INIT_MSG = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test-harness", "version": "0.1"},
    },
}
INITIALIZED_MSG = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
    "params": {},
}


def _exchange(*messages: dict) -> list[dict]:
    payload = "\n".join(json.dumps(m) for m in messages) + "\n"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(ROOT), str(ROOT / "src"), env.get("PYTHONPATH", "")) if p
    )
    env["AUDIAGENTIC_REPO_ROOT"] = str(ROOT)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "audiagentic.provisioning.mcp.server",
            "--readonly",
            "--smoke-only",
        ],
        input=payload,
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        env=env,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def test_stage0_exposes_only_smoke_tool():
    responses = _exchange(
        INIT_MSG,
        INITIALIZED_MSG,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )

    tool_resp = next(r for r in responses if r.get("id") == 2)
    names = {tool["name"] for tool in tool_resp["result"]["tools"]}

    assert names == {"audiagentic_smoke_status"}


def test_stage0_smoke_tool_reports_readonly_status():
    responses = _exchange(
        INIT_MSG,
        INITIALIZED_MSG,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "audiagentic_smoke_status", "arguments": {}},
        },
    )

    call_resp = next(r for r in responses if r.get("id") == 2)
    assert "error" not in call_resp
    blocks = call_resp["result"]["content"]
    payload = json.loads(blocks[0]["text"])
    result = payload.get("_result", payload)

    assert result["ok"] is True
    assert result["readonly"] is True
    assert result["smoke_only"] is True
    assert result["repo_root"] == str(ROOT)
