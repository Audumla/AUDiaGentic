"""AUDiaGentic project component MCP server.

Thin MCP layer — delegates all work to runtime/lifecycle and foundation.
Reads AUDIAGENTIC_REPO_ROOT from env to locate the target project.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

from audiagentic.foundation.components import all_descriptors, is_enabled, is_installed
from audiagentic.foundation.components.hooks import get_component_status
from audiagentic.foundation.components.ids import COMPONENT_PROJECT, COMPONENT_PROVIDERS
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.runtime.harness.pi.install import (
    build_runtime_sync,
    refresh_harness_config_if_installed,
)
from audiagentic.runtime.lifecycle.components import (
    disable_component,
    enable_component,
    install_component,
    uninstall_component,
)
from audiagentic.runtime.lifecycle.detector import detect_installed_state, get_project_version_info

register_all_components()


_PROJECT_ROOT: Path | None = None


def _project_root() -> Path:
    if _PROJECT_ROOT is not None:
        return _PROJECT_ROOT
    # Fallback for callers that don't pass --project-root
    repo_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if repo_root:
        return Path(repo_root)
    raise RuntimeError("Pass --project-root or set AUDIAGENTIC_REPO_ROOT")


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_PROJECT, "audiagentic-project")


def _server_instructions() -> str:
    decl = _server_decl()
    return (
        decl.instructions
        if decl and decl.instructions
        else (
            "AUDiaGentic project component server. "
            "Use project_status to inspect the target project, "
            "list_components to see all registered components and their status."
        )
    )


def _tool_description(name: str, fallback: str) -> str:
    decl = _server_decl()
    if decl and name in decl.tool_descriptions:
        return decl.tool_descriptions[name]
    return fallback


def build_server() -> FastMCP:
    mcp = FastMCP(
        "audiagentic-project",
        instructions=_server_instructions(),
    )

    @mcp.tool(description=_tool_description("project_status", "Return the current project installation state and installed components."))
    def project_status() -> dict[str, Any]:
        project_root = _project_root()
        state = detect_installed_state(project_root)
        components = {
            cid: {
                "status": "installed" if is_installed(cid, project_root) else "not-installed",
                "enabled": is_enabled(cid, project_root) if is_installed(cid, project_root) else None,
            }
            for cid in all_descriptors()
        }
        version_info = get_project_version_info(project_root) if state.state == "installed" else None
        component_details: dict[str, dict[str, Any]] = {}
        for component_id, descriptor in all_descriptors().items():
            if not is_installed(component_id, project_root):
                continue
            payload = get_component_status(descriptor, project_root)
            if payload:
                component_details[component_id] = payload
        return {
            "project_root": str(project_root),
            "install_state": state.state,
            "audiagentic_markers": state.audiagentic_markers,
            "components": components,
            "version_info": version_info,
            "component_details": component_details,
        }

    @mcp.tool(description=_tool_description("list_components", "List all registered AUDiaGentic components with install and enabled status."))
    def list_components() -> list[dict[str, Any]]:
        project_root = _project_root()
        rows: list[dict[str, Any]] = []
        for d in all_descriptors().values():
            row = {
                "component_id": d.component_id,
                "display_name": d.display_name,
                "description": d.description,
                "status": "installed" if is_installed(d.component_id, project_root) else "not-installed",
                "enabled": is_enabled(d.component_id, project_root) if is_installed(d.component_id, project_root) else None,
                "core": d.core,
                "detection_marker": d.detection_marker,
                "file_count": len(d.files),
            }
            if is_installed(d.component_id, project_root):
                payload = get_component_status(d, project_root)
                if payload:
                    row["component_status"] = payload
            rows.append(row)
        return rows

    @mcp.tool(description=_tool_description("install_component_tool", "Install a component into the target project."))
    def install_component_tool(component_id: str) -> dict[str, Any]:
        project_root = _project_root()
        result = install_component(component_id, project_root)
        if result.get("ok", True):
            refresh_harness_config_if_installed(project_root, reason="component-installed", component_id=component_id)
        return result

    @mcp.tool(description=_tool_description("uninstall_component_tool", "Uninstall a component from the target project."))
    def uninstall_component_tool(component_id: str, remove_configs: bool = False) -> dict[str, Any]:
        project_root = _project_root()
        descriptor = all_descriptors().get(component_id)
        if descriptor and descriptor.core:
            return {"ok": False, "error": f"cannot uninstall core component: {component_id}"}
        result = uninstall_component(component_id, project_root, remove_configs=remove_configs)
        if result.get("ok", True):
            refresh_harness_config_if_installed(project_root, reason="component-uninstalled", component_id=component_id)
        return result

    @mcp.tool(description=_tool_description("enable_component_tool", "Enable a component in the target project."))
    def enable_component_tool(component_id: str) -> dict[str, Any]:
        project_root = _project_root()
        result = enable_component(component_id, project_root)
        if result.get("ok", True):
            refresh_harness_config_if_installed(project_root, reason="component-enabled", component_id=component_id)
        return result

    @mcp.tool(description=_tool_description("disable_component_tool", "Disable a component in the target project."))
    def disable_component_tool(component_id: str) -> dict[str, Any]:
        project_root = _project_root()
        result = disable_component(component_id, project_root)
        if result.get("ok", True):
            refresh_harness_config_if_installed(project_root, reason="component-disabled", component_id=component_id)
        return result

    @mcp.tool(description=_tool_description("read_project_file", "Read a file inside the project .audiagentic directory."))
    def read_project_file(relative_path: str) -> dict[str, Any]:
        project_root = _project_root()
        rel = Path(relative_path)
        if not rel.parts or rel.parts[0] != ".audiagentic":
            return {"error": "path must start with .audiagentic/"}
        target = project_root / rel
        try:
            target = target.resolve()
            target.relative_to(project_root.resolve())
        except ValueError:
            return {"error": "path escapes project root"}
        if not target.exists():
            return {"error": f"not found: {relative_path}"}
        if not target.is_file():
            return {"error": f"not a file: {relative_path}"}
        text = target.read_text(encoding="utf-8")
        if target.suffix == ".json":
            try:
                return {"path": relative_path, "content": json.loads(text)}
            except json.JSONDecodeError:
                pass
        return {"path": relative_path, "content": text}

    @mcp.tool(description=_tool_description("runtime_sync_contract", "Return AUDiaGentic runtime sync contract and supported actions for Pi-aware clients."))
    def runtime_sync_contract() -> dict[str, Any]:
        return {
            "target": "pi-runtime",
            "actions": {
                "refresh_required": "Refresh local client state only.",
                "reload_required": "Reload Pi runtime after request completes.",
                "restart_required": "Prompt for full Pi session restart.",
            },
            "example": build_runtime_sync(reason="component-installed", component_id=COMPONENT_PROVIDERS),
        }

    return mcp


def main() -> int:
    import argparse

    global _PROJECT_ROOT
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-root", default=None)
    args, _ = parser.parse_known_args()
    if args.project_root:
        _PROJECT_ROOT = Path(args.project_root).resolve()

    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
