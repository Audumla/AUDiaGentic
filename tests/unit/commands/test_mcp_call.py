"""External CLI uses the registered MCP tools, not duplicate planning/ledger APIs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from audiagentic.commands.mcp import dispatch
from audiagentic.components.project.onboarding.call import _server_module, call_tool


def _args(*tail: str, project: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        command="mcp",
        tail=list(tail),
        project=project,
        component_profile=None,
        management_help=False,
    )


def test_cli_requires_explicit_project():
    with pytest.raises(SystemExit, match="2"):
        dispatch(
            _args("call", "ag-planning", "plan_get_item"), argparse.ArgumentParser()
        )


def test_cli_validates_json_payload(tmp_path: Path):
    with pytest.raises(SystemExit, match="2"):
        dispatch(
            _args(
                "call",
                "ag-planning",
                "plan_get_item",
                "arguments",
                "[]",
                "project",
                str(tmp_path),
            ),
            argparse.ArgumentParser(),
        )


def test_cli_calls_project_api_not_direct_plan_store(
    monkeypatch, tmp_path: Path, capsys
):
    from audiagentic.components.project import project_api

    observed = []

    def fake_call(*args):
        observed.append(args)
        return {"id": "EX01"}

    monkeypatch.setattr(project_api, "call_mcp_tool", fake_call)
    assert (
        dispatch(
            _args(
                "call",
                "ag-planning",
                "plan_get_item",
                "arguments",
                '{"item_id":"EX01"}',
                "project",
                str(tmp_path),
            ),
            argparse.ArgumentParser(),
        )
        == 0
    )
    assert observed == [(tmp_path, "ag-planning", "plan_get_item", {"item_id": "EX01"})]
    assert json.loads(capsys.readouterr().out) == {"id": "EX01"}


def test_cli_args_file(monkeypatch, tmp_path: Path, capsys):
    from audiagentic.components.project import project_api

    payload = tmp_path / "args.json"
    payload.write_text('{"group_by":"flat"}')
    observed = []
    monkeypatch.setattr(
        project_api,
        "call_mcp_tool",
        lambda *args: observed.append(args) or {"events": []},
    )
    assert (
        dispatch(
            _args(
                "call",
                "ag-ledger",
                "get_pending_events",
                "arguments-file",
                str(payload),
                "project",
                str(tmp_path),
            ),
            argparse.ArgumentParser(),
        )
        == 0
    )
    assert observed[0][3] == {"group_by": "flat"}
    assert json.loads(capsys.readouterr().out) == {"events": []}


def test_local_servers_resolve_from_project_declarations(tmp_path: Path):
    assert _server_module(tmp_path, "ag-planning").endswith("planning.planning_mcp")
    assert _server_module(tmp_path, "ag-ledger").endswith("ledger.ledger_mcp")
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    with pytest.raises(AudiaGenticError, match="Unknown locally declared MCP server"):
        _server_module(tmp_path, "not-a-local-server")


@pytest.mark.asyncio
async def test_real_mcp_planning_and_ledger_isolated_project(tmp_path: Path):
    """The actual server performs schema validation and writes only to the target root."""
    created = await call_tool(
        tmp_path,
        "ag-planning",
        "plan_create_item",
        {
            "item": {
                "id": "EXT01",
                "plan": "build-external-access",
                "title": "External accessor smoke",
                "validation": "Temporary fixture verified",
                "acceptance_criteria": "MCP round trip",
            }
        },
    )
    assert created["id"] == "EXT01"
    path = tmp_path / "docs/planning/active/build-external-access/EXT01.md"
    assert path.exists()
    fetched = await call_tool(
        tmp_path, "ag-planning", "plan_get_item", {"item_id": "EXT01"}
    )
    assert fetched["id"] == "EXT01"

    grouped = await call_tool(
        tmp_path,
        "ag-planning",
        "plan_list_items",
        {"plan": "build-external-access"},
    )
    assert grouped["total"] == 1

    pending = await call_tool(
        tmp_path, "ag-ledger", "get_pending_events", {"group_by": "flat"}
    )
    assert "events" in pending


@pytest.mark.asyncio
async def test_real_mcp_schema_rejection_does_not_create_document(tmp_path: Path):
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    with pytest.raises(AudiaGenticError):
        await call_tool(
            tmp_path,
            "ag-planning",
            "plan_create_item",
            {
                "item": {
                    "id": "bad/path",
                    "plan": "build-external-access",
                    "title": "Invalid",
                }
            },
        )
    assert not (tmp_path / "docs/planning/active/build-external-access").exists()


@pytest.mark.asyncio
async def test_real_mcp_unknown_tool_is_failure(tmp_path: Path):
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    with pytest.raises(AudiaGenticError, match="VAL-MCPONB-004: Unknown tool"):
        await call_tool(tmp_path, "ag-ledger", "not_a_ledger_tool", {})
