"""CLI visibility config helpers for the core session component."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.runtime.config import load_layered_config, load_yaml_file, save_yaml_file


def config_path(scope: str, project_root: Path) -> Path:
    if scope == "project":
        return project_root / ".audiagentic" / "config" / "harness" / "ag.yaml"
    if scope == "global":
        from audiagentic.runtime.home import audiagentic_home

        return audiagentic_home() / "config" / "harness" / "ag.yaml"
    raise RuntimeError(f"unsupported scope: {scope}")


def effective_cli_visibility(project_root: Path) -> dict[str, bool]:
    from audiagentic.runtime.harness import default_config_path

    cfg = load_layered_config(
        pkg_default_path=default_config_path(),
        project_root=project_root,
        namespace="harness/ag",
    )
    ui = cfg.get("ui", {}) or {}
    return {
        "show_thinking_blocks": not bool(ui.get("hide_thinking_block", False)),
        "show_tool_blocks": not bool(ui.get("hide_tool_use", False)),
    }


def set_cli_visibility(
    *,
    project_root: Path,
    show_thinking_blocks: bool | None,
    show_tool_blocks: bool | None,
    scope: str,
) -> dict[str, Any]:
    if show_thinking_blocks is None and show_tool_blocks is None:
        raise RuntimeError("at least one visibility toggle must be provided")

    path = config_path(scope, project_root)
    if not path.exists():
        raise RuntimeError(f"missing harness config: {path}")

    current = load_yaml_file(path)
    ui = current.get("ui")
    if ui is None:
        ui = {}
        current["ui"] = ui
    if not isinstance(ui, dict):
        raise RuntimeError(f"invalid ui config mapping: {path}")

    updates: dict[str, bool] = {}
    if show_thinking_blocks is not None:
        ui["hide_thinking_block"] = not show_thinking_blocks
        updates["show_thinking_blocks"] = show_thinking_blocks
    if show_tool_blocks is not None:
        ui["hide_tool_use"] = not show_tool_blocks
        updates["show_tool_blocks"] = show_tool_blocks

    save_yaml_file(path, current, sort_keys=False)

    from audiagentic.runtime.harness import (
        build_runtime_sync,
        refresh_materialized_agent_config,
        request_runtime_reload,
    )
    from audiagentic.runtime.home import global_harness_runtime

    refresh_materialized_agent_config(global_harness_runtime(), project_root=project_root)
    request_runtime_reload(project_root, reason="session-ui-visibility-updated")

    return {
        "ok": True,
        "scope": scope,
        "config_path": str(path),
        "updated": updates,
        "effective": effective_cli_visibility(project_root),
        "sync": build_runtime_sync(reason="session-ui-visibility-updated"),
    }
