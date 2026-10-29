"""CFG08: setup registers worktree-scoped MCP servers at a harness's user scope.

The claude CLI is a stub on PATH that edits ``$CLAUDE_CONFIG_DIR/.claude.json``
as ``claude mcp add-json/remove --scope user`` would, so the real reader,
writer, ownership registry and fragment engine run end to end.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

from audiagentic.commands.doctor import run_doctor_command
from audiagentic.components.project import project_api
from audiagentic.components.project.doctor_checks import check_user_mcp
from audiagentic.components.project.onboarding.user_scope import user_scope_request
from audiagentic.foundation.contracts.errors import AudiaGenticError

SERVERS = {"ag-planning", "ag-ledger", "ag-agents-gateway"}

_STUB = """#!{python}
import json, os, sys
path = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], ".claude.json")
data = json.load(open(path)) if os.path.exists(path) else {{"numStartups": 7}}
servers = data.setdefault("mcpServers", {{}})
_, action, *rest = sys.argv[1:]
assert rest[:2] == ["--scope", "user"], rest
name = rest[2]
if action == "add-json":
    if name in servers:
        sys.exit("already exists")
    servers[name] = json.loads(rest[3])
elif action == "remove":
    servers.pop(name)
json.dump(data, open(path, "w"))
with open(path + ".calls", "a") as log:
    log.write(action + " " + name + "\\n")
"""


@pytest.fixture
def claude(tmp_path: Path, monkeypatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "claude"
    stub.write_text(_STUB.format(python=sys.executable))
    stub.chmod(0o755)
    config = tmp_path / "claude-config"
    config.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}:{Path(sys.executable).parent}:/usr/bin:/bin")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    return config / ".claude.json"


def _servers(path: Path) -> dict:
    return json.loads(path.read_text())["mcpServers"]


def test_request_holds_only_worktree_scoped_servers_without_env():
    request = user_scope_request()
    assert {entry.name for entry in request.entries} == SERVERS
    for entry in request.entries:
        assert Path(entry.command).name == "audiagentic" and Path(entry.command).is_absolute()
        assert entry.args[0] == "mcp" and entry.env == ()


def test_setup_registers_through_the_cli_and_is_idempotent(claude: Path):
    first = project_api.setup_user_mcp(["claude"])
    assert first[0]["ok"] and set(first[0]["updated"]) == SERVERS
    servers = _servers(claude)
    assert set(servers) == SERVERS
    assert all(entry["type"] == "stdio" and entry["env"] == {} for entry in servers.values())
    assert json.loads(claude.read_text())["numStartups"] == 7  # Claude's own state is kept

    calls = Path(f"{claude}.calls").read_text()
    again = project_api.setup_user_mcp(["claude"])
    assert again[0]["ok"] and not again[0]["changed"]
    assert Path(f"{claude}.calls").read_text() == calls  # nothing rewritten

    assert all(entry["state"] == "configured" for entry in project_api.setup_user_mcp(["claude"], dry_run=True)[0]["entries"])
    assert [result.status for result in check_user_mcp(None)] == ["ok"]


def test_foreign_entries_are_reported_never_overwritten(claude: Path):
    claude.write_text(json.dumps({"mcpServers": {"ag-planning": {"type": "stdio", "command": "mine", "args": []}}}))
    result = project_api.setup_user_mcp(["claude"])[0]
    assert not result["ok"] and result["collisions"][0]["desired_name"] == "ag-planning"
    assert _servers(claude) == {"ag-planning": {"type": "stdio", "command": "mine", "args": []}}
    states = {entry["name"]: entry["state"] for entry in project_api.setup_user_mcp(["claude"], dry_run=True)[0]["entries"]}
    assert states == {"ag-planning": "foreign", "ag-ledger": "missing", "ag-agents-gateway": "missing"}
    assert check_user_mcp(None)[0].message == "no user-scope MCP registration (optional)"


def test_drift_is_reported_by_doctor_and_repaired_by_setup(claude: Path):
    project_api.setup_user_mcp(["claude"])
    data = json.loads(claude.read_text())
    data["mcpServers"]["ag-ledger"]["args"] = ["edited"]
    claude.write_text(json.dumps(data))
    [result] = check_user_mcp(None)
    assert result.status == "warn" and "ag-ledger drifted" in result.message
    assert result.fix == "audiagentic setup harness claude"
    assert set(project_api.setup_user_mcp(["claude"])[0]["updated"]) == {"ag-ledger"}
    assert check_user_mcp(None)[0].status == "ok"


def test_unsupported_harness_is_refused(claude: Path):
    with pytest.raises(AudiaGenticError) as raised:
        project_api.setup_user_mcp(["codex"])
    assert raised.value.code == "VAL-MCPUSR-001"


def test_setup_command_clauses(claude: Path, capsys):
    args = argparse.Namespace(command="setup", project=None, as_json=True, clauses=["harness", "claude", "dry-run"])
    run_doctor_command(args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] == [] and payload["mcp"][0]["provider_id"] == "claude"
    assert not claude.exists()  # dry run writes nothing
    with pytest.raises(SystemExit, match="unknown or repeated clause"):
        run_doctor_command(argparse.Namespace(command="setup", project=None, as_json=True, clauses=["harnesses"]))


def test_claude_project_path_has_no_user_fallback():
    from audiagentic.components.providers.adapters.claude.config import resolve_claude_mcp_config_path

    with pytest.raises(AudiaGenticError) as raised:
        resolve_claude_mcp_config_path(None)
    assert raised.value.code == "VAL-CLAUDECFG-001"
