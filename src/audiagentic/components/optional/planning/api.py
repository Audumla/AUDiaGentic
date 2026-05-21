"""Planning component API.

MCP/CLI surfaces should delegate here instead of embedding filesystem logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PLANNING_CONFIG_PATH = Path(".audiagentic") / "planning" / "config" / "planning.yaml"
INDEXES_PATH = Path(".audiagentic") / "planning" / "indexes"
META_PATH = Path(".audiagentic") / "planning" / "meta"
EVENTS_PATH = Path(".audiagentic") / "planning" / "events" / "events.jsonl"
INDEX_KINDS = ("requests", "specifications", "plans", "tasks", "work-packages", "standards")
READABLE_INDEXES = {
    "requests", "specifications", "plans", "tasks",
    "work-packages", "standards", "lookup", "readiness",
    "dispatch", "trace", "claims",
}


def planning_installed(project_root: Path) -> bool:
    return (project_root / PLANNING_CONFIG_PATH).exists()


def index_counts(project_root: Path) -> dict[str, int]:
    indexes_dir = project_root / INDEXES_PATH
    counts: dict[str, int] = {}
    for kind in INDEX_KINDS:
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


def counter_values(project_root: Path) -> dict[str, int]:
    counters_file = project_root / ".audiagentic" / "planning" / "ids" / "counters.json"
    if not counters_file.exists():
        return {}
    try:
        return json.loads(counters_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def planning_status(project_root: Path) -> dict[str, Any]:
    installed = planning_installed(project_root)
    docs_dir = project_root / "docs" / "planning"
    result: dict[str, Any] = {
        "project_root": str(project_root),
        "installed": installed,
        "config_path": str(PLANNING_CONFIG_PATH),
        "docs_dir_exists": docs_dir.exists(),
    }
    if installed:
        result["indexes_dir_exists"] = (project_root / INDEXES_PATH).exists()
        result["meta_dir_exists"] = (project_root / META_PATH).exists()
        result["events_file_exists"] = (project_root / EVENTS_PATH).exists()
    return result


def planning_summary(project_root: Path) -> dict[str, Any]:
    if not planning_installed(project_root):
        return {"installed": False, "counts": {}, "counters": {}}
    return {
        "installed": True,
        "counts": index_counts(project_root),
        "counters": counter_values(project_root),
    }


def planning_index(project_root: Path, index_name: str) -> dict[str, Any]:
    if index_name not in READABLE_INDEXES:
        return {"error": f"unknown index: {index_name}. Valid: {sorted(READABLE_INDEXES)}"}
    if not planning_installed(project_root):
        return {"error": "planning not installed in this project"}
    index_file = project_root / INDEXES_PATH / f"{index_name}.json"
    if not index_file.exists():
        return {"error": f"index file not found: {index_name}.json"}
    try:
        return {"index": index_name, "content": json.loads(index_file.read_text(encoding="utf-8"))}
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": str(exc)}


def planning_events(project_root: Path, limit: int = 20) -> dict[str, Any]:
    events_file = project_root / EVENTS_PATH
    if not events_file.exists():
        return {"events": [], "total_lines": 0}
    lines = events_file.read_text(encoding="utf-8").splitlines()
    tail = lines[-limit:] if limit > 0 else lines
    events: list[dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"raw": line})
    return {"events": events, "total_lines": len(lines)}
