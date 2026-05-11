"""AUDiaGentic project component MCP server.

Exposes project status and available component inventory to the Pi TUI.
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

from audiagentic.runtime.lifecycle.detector import detect_installed_state
from audiagentic.runtime.lifecycle.manifest import read_manifest

# Components that can be installed into a project and how to detect them.
_COMPONENTS: dict[str, dict[str, Any]] = {
    "planning": {
        "description": "Structured planning system (requests, specs, tasks, plans, work-packages)",
        "detect": lambda root: (root / ".audiagentic" / "planning" / "config" / "planning.yaml").exists(),
        "docs_dir": "docs/planning",
    },
    "providers": {
        "description": "AI provider runtime configuration and model catalogs",
        "detect": lambda root: (root / ".audiagentic" / "runtime" / "providers").exists(),
        "runtime_dir": ".audiagentic/runtime/providers",
    },
    "release": {
        "description": "Release management and audit ledger",
        "detect": lambda root: (root / ".audiagentic" / "release").exists(),
        "runtime_dir": ".audiagentic/release",
    },
}


def _project_root() -> Path:
    repo_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if not repo_root:
        raise RuntimeError("AUDIAGENTIC_REPO_ROOT not set")
    return Path(repo_root)


def _detect_components(project_root: Path) -> dict[str, str]:
    return {
        name: ("installed" if meta["detect"](project_root) else "not-installed")
        for name, meta in _COMPONENTS.items()
    }


def build_server() -> FastMCP:
    mcp = FastMCP(
        "audiagentic-project",
        instructions=(
            "AUDiaGentic project component server. "
            "Use project_status to inspect the target project, "
            "list_components to see what can be installed."
        ),
    )

    @mcp.tool(description="Return the current project installation state and installed components.")
    def project_status() -> dict[str, Any]:
        project_root = _project_root()
        state = detect_installed_state(project_root)
        components = _detect_components(project_root)

        manifest: dict[str, Any] | None = None
        if state.state == "audiagentic-current":
            try:
                m = read_manifest(project_root)
                manifest = {
                    "current_version": m.current_version,
                    "installation_kind": m.installation_kind,
                    "components": m.components,
                    "providers": m.providers,
                    "last_lifecycle_action": m.last_lifecycle_action,
                    "updated_at": m.updated_at,
                }
            except Exception as exc:  # noqa: BLE001
                manifest = {"error": str(exc)}

        return {
            "project_root": str(project_root),
            "install_state": state.state,
            "audiagentic_markers": state.audiagentic_markers,
            "legacy_markers": state.legacy_markers,
            "components": components,
            "manifest": manifest,
        }

    @mcp.tool(description="List all available AUDiaGentic components with install status.")
    def list_components() -> list[dict[str, Any]]:
        project_root = _project_root()
        result = []
        for name, meta in _COMPONENTS.items():
            installed = meta["detect"](project_root)
            entry: dict[str, Any] = {
                "name": name,
                "description": meta["description"],
                "status": "installed" if installed else "not-installed",
            }
            for key in ("docs_dir", "runtime_dir"):
                if key in meta:
                    entry[key] = meta[key]
            result.append(entry)
        return result

    @mcp.tool(description="Read a file inside the project .audiagentic directory (read-only).")
    def read_project_file(relative_path: str) -> dict[str, Any]:
        """relative_path is relative to the project root, must start with .audiagentic/."""
        project_root = _project_root()
        rel = Path(relative_path)
        if not rel.parts or rel.parts[0] != ".audiagentic":
            return {"error": "path must start with .audiagentic/"}
        target = project_root / rel
        try:
            target = target.resolve()
            project_root_resolved = project_root.resolve()
            target.relative_to(project_root_resolved)  # containment check
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
    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
