"""AUDiaGentic planning component MCP server.

Exposes planning status and item counts to the Pi TUI.
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

_PLANNING_CONFIG_PATH = Path(".audiagentic") / "planning" / "config" / "planning.yaml"
_INDEXES_PATH = Path(".audiagentic") / "planning" / "indexes"
_META_PATH = Path(".audiagentic") / "planning" / "meta"

_INDEX_KINDS = ("requests", "specifications", "plans", "tasks", "work-packages", "standards")


def _project_root() -> Path:
    repo_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if not repo_root:
        raise RuntimeError("AUDIAGENTIC_REPO_ROOT not set")
    return Path(repo_root)


def _planning_installed(project_root: Path) -> bool:
    return (project_root / _PLANNING_CONFIG_PATH).exists()


def _index_counts(project_root: Path) -> dict[str, int]:
    indexes_dir = project_root / _INDEXES_PATH
    counts: dict[str, int] = {}
    for kind in _INDEX_KINDS:
        index_file = indexes_dir / f"{kind}.json"
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
                items = data if isinstance(data, list) else data.get("items", [])
                counts[kind] = len(items)
            except (json.JSONDecodeError, OSError):
                counts[kind] = -1
        else:
            counts[kind] = 0
    return counts


def _counter_values(project_root: Path) -> dict[str, int]:
    counters_file = project_root / ".audiagentic" / "planning" / "ids" / "counters.json"
    if not counters_file.exists():
        return {}
    try:
        return json.loads(counters_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def build_server() -> FastMCP:
    mcp = FastMCP(
        "audiagentic-planning",
        instructions=(
            "AUDiaGentic planning component server. "
            "Use planning_status to check whether planning is configured, "
            "planning_summary to get item counts per kind, "
            "planning_index to read a specific planning index."
        ),
    )

    @mcp.tool(description="Return planning component installation status for the project.")
    def planning_status() -> dict[str, Any]:
        project_root = _project_root()
        installed = _planning_installed(project_root)
        docs_dir = project_root / "docs" / "planning"
        result: dict[str, Any] = {
            "project_root": str(project_root),
            "installed": installed,
            "config_path": str(_PLANNING_CONFIG_PATH),
            "docs_dir_exists": docs_dir.exists(),
        }
        if installed:
            result["indexes_dir_exists"] = (project_root / _INDEXES_PATH).exists()
            result["meta_dir_exists"] = (project_root / _META_PATH).exists()
            result["events_file_exists"] = (
                project_root / ".audiagentic" / "planning" / "events" / "events.jsonl"
            ).exists()
        return result

    @mcp.tool(description="Return item counts per planning kind and current ID counters.")
    def planning_summary() -> dict[str, Any]:
        project_root = _project_root()
        if not _planning_installed(project_root):
            return {"installed": False, "counts": {}, "counters": {}}
        return {
            "installed": True,
            "counts": _index_counts(project_root),
            "counters": _counter_values(project_root),
        }

    @mcp.tool(description="Read a specific planning index (requests, specifications, plans, tasks, work-packages, standards, lookup, readiness, dispatch, trace, claims).")
    def planning_index(index_name: str) -> dict[str, Any]:
        valid = {
            "requests", "specifications", "plans", "tasks",
            "work-packages", "standards", "lookup", "readiness",
            "dispatch", "trace", "claims",
        }
        if index_name not in valid:
            return {"error": f"unknown index: {index_name}. Valid: {sorted(valid)}"}
        project_root = _project_root()
        if not _planning_installed(project_root):
            return {"error": "planning not installed in this project"}
        index_file = project_root / _INDEXES_PATH / f"{index_name}.json"
        if not index_file.exists():
            return {"error": f"index file not found: {index_name}.json"}
        try:
            return {"index": index_name, "content": json.loads(index_file.read_text(encoding="utf-8"))}
        except (json.JSONDecodeError, OSError) as exc:
            return {"error": str(exc)}

    @mcp.tool(description="Return recent planning events (last N lines from events.jsonl).")
    def planning_events(limit: int = 20) -> dict[str, Any]:
        project_root = _project_root()
        events_file = project_root / ".audiagentic" / "planning" / "events" / "events.jsonl"
        if not events_file.exists():
            return {"events": [], "total_lines": 0}
        lines = events_file.read_text(encoding="utf-8").splitlines()
        tail = lines[-limit:] if limit > 0 else lines
        events = []
        for line in tail:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"raw": line})
        return {"events": events, "total_lines": len(lines)}

    return mcp


def main() -> int:
    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
