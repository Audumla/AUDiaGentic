"""Disposable CLI/native-config/MCP protocol qualification for an installed application.

Run with the interpreter being qualified. --installed rejects checkout imports.
No real user HOME, native client, gateway or browser session is used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import validate
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def payload(result):
    if result.isError:
        raise AssertionError(result.content)
    value = result.structuredContent
    if value is None:
        blocks = [json.loads(c.text) for c in result.content if c.type == "text"]
        value = blocks[0] if len(blocks) == 1 else blocks
    if isinstance(value, dict) and set(value) == {"result"}:
        return value["result"]
    return value


@asynccontextmanager
async def connect(command, args, env, root):
    parameters = StdioServerParameters(command=command, args=list(args), env=env, cwd=str(root))
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            yield session


def qualify_native_clients(root, home, env):
    """Run read-only client discovery in the disposable, trusted fixture only."""
    results = {}
    (root / ".git").mkdir(exist_ok=True)
    codex_home = home / ".codex"
    codex_home.mkdir()
    import tomli_w

    (codex_home / "config.toml").write_text(
        tomli_w.dumps({"projects": {str(root): {"trust_level": "trusted"}}}), encoding="utf8"
    )
    child_env = {
        **env,
        "CODEX_HOME": str(codex_home),
        "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_DISABLE_MODELS_FETCH": "true",
        "PI_OFFLINE": "1",
    }
    for name, args in (
        ("codex", ["mcp", "list", "--json"]),
        ("opencode", ["mcp", "list", "--pure"]),
    ):
        executable = shutil.which(name)
        if executable is None:
            results[name] = "unavailable"
            continue
        run = subprocess.run(
            [executable, *args],
            cwd=root,
            env=child_env,
            capture_output=True,
            text=True,
            encoding="utf8",
            errors="replace",
            timeout=90,
        )
        assert run.returncode == 0, (name, run.stderr[-1000:])
        assert "ag-planning" in run.stdout, (name, run.stdout[-1000:])
        if name == "opencode":
            assert "connected" in run.stdout.lower(), (name, run.stdout[-1000:])
            results[name] = "connected"
        else:
            rows = json.loads(run.stdout)
            assert any(row.get("name") == "ag-planning" and row.get("enabled") for row in rows)
            results[name] = "recognized"
    # Pi's installed CLI has no read-only MCP listing command; format/protocol
    # proof alone cannot establish discovery by its optional MCP extension.
    results["pi"] = "no_readonly_discovery_command"
    return results


async def qualify(installed=False, native_clients=False):
    import audiagentic

    origin = Path(audiagentic.__file__).resolve()
    if installed:
        assert origin.is_relative_to(Path(sys.prefix).resolve()), origin
        assert "site-packages" in origin.parts, origin
    with TemporaryDirectory(prefix="audiagentic-onboarding-") as directory:
        root = Path(directory)
        home = root / "isolated-home"
        home.mkdir()
        env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "AUDIAGENTIC_REPO_ROOT": str(root),
            "AUDIAGENTIC_HOME": str(home / ".audiagentic"),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "APPDATA": str(home / "AppData/Roaming"),
            "LOCALAPPDATA": str(home / "AppData/Local"),
        }
        env.pop("AUDIAGENTIC_COMPONENT_PROFILE", None)

        def cli(*tokens):
            result = subprocess.run(
                [sys.executable, "-m", "audiagentic.launcher", *tokens],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf8",
                timeout=60,
            )
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)

        rows = cli("mcp", "list", "output", "json")
        assert any(row["mcp_id"] == "ag-planning" for row in rows)
        first = cli(
            "mcp",
            "install",
            "ag-planning",
            "harness",
            "pi,opencode,codex",
            "project",
            str(root),
            "non-interactive",
            "output",
            "json",
        )
        assert first["ok"]
        natives = [
            root / ".pi/mcp.json",
            root / ".opencode/opencode.json",
            root / ".codex/config.toml",
        ]
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in natives]
        again = cli(
            "mcp",
            "install",
            "ag-planning",
            "harness",
            "pi,opencode,codex",
            "project",
            str(root),
            "non-interactive",
            "output",
            "json",
        )
        assert again["ok"] and not again["changed"]
        assert before == [(p.read_bytes(), p.stat().st_mtime_ns) for p in natives]
        ledger = cli(
            "mcp",
            "install",
            "ag-ledger",
            "harness",
            "pi",
            "project",
            str(root),
            "non-interactive",
            "output",
            "json",
        )
        assert ledger["ok"]
        async with connect(
            sys.executable,
            ["-m", "audiagentic.launcher", "mcp", "audiagentic.components.project.project_mcp"],
            env,
            root,
        ) as session:
            tools = {t.name: t for t in (await session.list_tools()).tools}
            assert len(tools) == 22
            assert tools["install_mcp"].inputSchema["properties"]["harness_ids"]["description"]
            status = await session.call_tool("get_mcp_install_status", {})
            assert status.content == []
            validate(status.structuredContent, tools["get_mcp_install_status"].outputSchema)
            assert payload(status) == {"has_unresolved_operation": False}
            catalog = await session.call_tool("list_mcp_catalog", {"mcp_id": "ag-planning"})
            assert catalog.content == []
            assert payload(catalog)["mcp_id"] == "ag-planning"
            dry = await session.call_tool(
                "install_mcp",
                {
                    "mcp_id": "ag-planning",
                    "harness_ids": ["pi", "opencode", "codex"],
                    "dry_run": True,
                },
            )
            assert dry.content == [] and not payload(dry)["changed"]
            legacy = await session.call_tool("list_components", {})
            assert legacy.content  # Unchanged nonempty legacy text channel.
        servers = json.loads((root / ".pi/mcp.json").read_text(encoding="utf8"))["mcpServers"]
        planning = servers["ag-planning"]
        async with connect(
            planning["command"], planning["args"], {**env, **planning.get("env", {})}, root
        ) as session:
            tools = {t.name for t in (await session.list_tools()).tools}
            assert "plan_create_item" in tools
            created = payload(
                await session.call_tool(
                    "plan_create_item",
                    {"item": {"plan": "onboarding-proof", "title": "Disposable protocol proof"}},
                )
            )
            identity = created["id"]
            assert not (await session.call_tool("plan_get_item", {"item_id": identity})).isError
            assert not (
                await session.call_tool(
                    "plan_update_item",
                    {"item_id": identity, "updates": {"notes": "Protocol roundtrip"}, "append": []},
                )
            ).isError
            assert not (await session.call_tool("plan_delete_item", {"item_id": identity})).isError
        entry = servers["ag-ledger"]
        async with connect(
            entry["command"], entry["args"], {**env, **entry.get("env", {})}, root
        ) as session:
            event = payload(
                await session.call_tool(
                    "record_change_event",
                    {
                        "event": {
                            "change-class": "tests",
                            "files": ["proof.txt"],
                            "technical-summary": "Disposable MCP proof",
                            "user-summary-candidate": "Disposable proof",
                            "status": "unreleased",
                        }
                    },
                )
            )
            assert event.get("event-id")
            assert not (
                await session.call_tool("get_fragment", {"event_id": event["event-id"]})
            ).isError
        recognition = qualify_native_clients(root, home, env) if native_clients else "not_assessed"
        return {
            "cli": "passed",
            "native_formats": ["pi-json", "opencode-json", "codex-toml"],
            "protocol": ["project", "planning-crud", "ledger-roundtrip"],
            "installed_origin": str(origin) if installed else "source",
            "native_client_recognition": recognition,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--native-clients", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(qualify(args.installed, args.native_clients)), indent=2))
