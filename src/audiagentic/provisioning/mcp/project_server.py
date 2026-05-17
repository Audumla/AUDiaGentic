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

import yaml

from audiagentic.foundation.components import all_descriptors, is_enabled, is_installed
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.runtime.lifecycle.components import (
    disable_component,
    enable_component,
    install_component,
    uninstall_component,
)
from audiagentic.runtime.lifecycle.detector import detect_installed_state

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


def build_server() -> FastMCP:
    mcp = FastMCP(
        "audiagentic-project",
        instructions=(
            "AUDiaGentic project component server. "
            "Use project_status to inspect the target project, "
            "list_components to see all registered components and their status."
        ),
    )

    @mcp.tool(description="Return the current project installation state and installed components.")
    def project_status() -> dict[str, Any]:
        project_root = _project_root()
        state = detect_installed_state(project_root)
        components = {
            cid: {
                "status": "installed" if is_installed(cid, project_root) else "not-installed",
                "enabled": is_enabled(cid, project_root),
            }
            for cid in all_descriptors()
        }
        version_info: dict[str, Any] | None = None
        if state.state == "installed":
            try:
                marker_path = project_root / ".audiagentic" / "components" / "core-lifecycle.yaml"
                if marker_path.exists():
                    marker_data = yaml.safe_load(marker_path.read_text(encoding="utf-8")) or {}
                    version_info = {
                        "version": marker_data.get("version"),
                        "installation_kind": marker_data.get("installation-kind"),
                        "last_lifecycle_action": marker_data.get("last-lifecycle-action"),
                        "installed_at": marker_data.get("installed-at"),
                    }
            except Exception as exc:  # noqa: BLE001
                version_info = {"error": str(exc)}
        return {
            "project_root": str(project_root),
            "install_state": state.state,
            "audiagentic_markers": state.audiagentic_markers,
            "components": components,
            "version_info": version_info,
        }

    @mcp.tool(description="List all registered AUDiaGentic components with install and enabled status.")
    def list_components() -> list[dict[str, Any]]:
        project_root = _project_root()
        return [
            {
                "component_id": d.component_id,
                "display_name": d.display_name,
                "description": d.description,
                "status": "installed" if is_installed(d.component_id, project_root) else "not-installed",
                "enabled": is_enabled(d.component_id, project_root),
                "detection_marker": d.detection_marker,
                "file_count": len(d.files),
            }
            for d in all_descriptors().values()
        ]

    @mcp.tool(description="Install a component into the target project.")
    def install_component_tool(component_id: str) -> dict[str, Any]:
        return install_component(component_id, _project_root())

    @mcp.tool(description="Uninstall a component from the target project.")
    def uninstall_component_tool(component_id: str, remove_configs: bool = False) -> dict[str, Any]:
        deleted = uninstall_component(component_id, _project_root(), remove_configs=remove_configs)
        return {"ok": True, "component_id": component_id, "deleted": [str(p) for p in deleted]}

    @mcp.tool(description="Enable a component in the target project.")
    def enable_component_tool(component_id: str) -> dict[str, Any]:
        return enable_component(component_id, _project_root())

    @mcp.tool(description="Disable a component in the target project.")
    def disable_component_tool(component_id: str) -> dict[str, Any]:
        return disable_component(component_id, _project_root())

    @mcp.tool(description="Read a file inside the project .audiagentic directory (read-only).")
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
