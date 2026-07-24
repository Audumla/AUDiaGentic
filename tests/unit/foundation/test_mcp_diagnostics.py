from __future__ import annotations

import sys
from pathlib import Path

from audiagentic.foundation.mcp.diagnostics import probe_mcp_server

_OK_SERVER = """
import sys
line = sys.stdin.readline()
sys.stdout.write('{"jsonrpc": "2.0", "id": 1, "result": {}}\\n')
sys.stdout.flush()
sys.stdin.readline()
"""

_CRASH_SERVER = """
import sys
sys.exit(3)
"""

_HANG_SERVER = """
import time
time.sleep(30)
"""

_MALFORMED_SERVER = """
import sys
sys.stdin.readline()
sys.stdout.write("not json\\n")
sys.stdout.flush()
sys.stdin.readline()
"""


def _script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_probe_reports_ok_on_successful_initialize(tmp_path: Path) -> None:
    script = _script(tmp_path, "ok_server.py", _OK_SERVER)

    result = probe_mcp_server("ag-ok", [sys.executable, str(script)], timeout=5.0)

    assert result == {
        "server_name": "ag-ok",
        "ok": True,
        "phase": "initialization",
        "elapsed_ms": result["elapsed_ms"],
    }
    assert isinstance(result["elapsed_ms"], int)


def test_probe_reports_crashed_when_process_exits_without_response(tmp_path: Path) -> None:
    script = _script(tmp_path, "crash_server.py", _CRASH_SERVER)

    result = probe_mcp_server("ag-crash", [sys.executable, str(script)], timeout=5.0)

    assert result["server_name"] == "ag-crash"
    assert result["ok"] is False
    assert result["error"] == "crashed"
    assert result["exit_status"] == 3


def test_probe_reports_timeout_when_no_response_in_time(tmp_path: Path) -> None:
    script = _script(tmp_path, "hang_server.py", _HANG_SERVER)

    result = probe_mcp_server("ag-hang", [sys.executable, str(script)], timeout=0.5)

    assert result["server_name"] == "ag-hang"
    assert result["ok"] is False
    assert result["error"] == "initialize-timeout"


def test_probe_reports_rejected_on_malformed_response(tmp_path: Path) -> None:
    script = _script(tmp_path, "malformed_server.py", _MALFORMED_SERVER)

    result = probe_mcp_server("ag-malformed", [sys.executable, str(script)], timeout=5.0)

    assert result["server_name"] == "ag-malformed"
    assert result["ok"] is False
    assert result["error"] == "initialize-rejected"


def test_probe_reports_spawn_failed_for_nonexistent_command(tmp_path: Path) -> None:
    result = probe_mcp_server(
        "ag-missing", [str(tmp_path / "does-not-exist-binary")], timeout=1.0
    )

    assert result["server_name"] == "ag-missing"
    assert result["ok"] is False
    assert result["error"] == "spawn-failed"

    # Never leaks argv/env into the result -- only the caller-supplied name.
    assert "command" not in result
    assert "env" not in result
