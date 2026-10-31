"""Move feature-state shards into settings, transactionally, with a rollback.

``plan_shard_migration`` reads the legacy shards (and the pre-shard ``features.yaml``) and returns
the settings patch they imply, the keys it would overwrite, and legacy fields it does not
understand. ``apply_shard_migration`` stages verified backups, writes a manifest, applies the
patch under the settings writer's lock, and only then removes the sources. ``rollback_shard_migration``
restores a key only while it still holds the value the migration wrote, so later edits survive.

The shards are gitignored, per-host files. A provider's legacy ``enabled`` is what lifecycle and
reconciliation applied on this host, so it becomes a local observation (``providers`` /
``<id>.enabled``), never a ``providers.<id>.enabled`` policy: that key is the user's own override
in tracked settings and wins over the observation. Everything else (feature intent, options)
lands in ``features``. A different value already present is reported as a conflict, never merged over.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audiagentic.foundation.config.settings import scope_sources
from audiagentic.foundation.config.strict_yaml import load_settings_text
from audiagentic.foundation.config.writer import write_settings_patch
from audiagentic.foundation.io import atomic_write_bytes, load_yaml_file
from audiagentic.foundation.paths.names import PROJECT_MARKER_NAME

from .observations import clear_observation, get_observation, record_observation
from .state import (
    LEGACY_FEATURE_STATE_PATH,
    SHARD_DIR,
    migrate_component_state_to_flat,
)

MIGRATIONS_DIR = Path(PROJECT_MARKER_NAME) / "state" / "migrations"
MANIFEST_VERSION = 1
PROVIDERS = "providers"
_KNOWN_COMPONENT_KEYS = {"features", "implementations"}
_KNOWN_IMPLEMENTATION_KEYS = {"enabled", "options", "features"}
_KNOWN_FEATURE_KEYS = {"enabled", "options"}

Path_ = tuple[str, ...]


@dataclass(frozen=True)
class MigrationPlan:
    sources: tuple[Path, ...]
    values: dict[Path_, Any]  # settings key path -> value to set
    observations: dict[tuple[str, str], Any] = field(default_factory=dict)  # (component, key) -> value
    conflicts: dict[tuple[str, ...], tuple[Any, Any]] = field(default_factory=dict)  # path -> (existing, planned)
    unknown: tuple[str, ...] = ()

    @property
    def patch(self) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        for path, value in self.values.items():
            node = patch
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = value
        return patch

    @property
    def empty(self) -> bool:
        return not self.sources


def _legacy_sources(project_root: Path) -> list[Path]:
    shards = sorted((project_root / SHARD_DIR).glob("*.yaml")) if (project_root / SHARD_DIR).is_dir() else []
    legacy = project_root / LEGACY_FEATURE_STATE_PATH
    return [*shards, *([legacy] if legacy.is_file() else [])]


def _load_states(project_root: Path) -> tuple[dict[str, dict[str, Any]], list[Path], list[str]]:
    """Component states by id. A shard wins over the pre-shard file for the same component."""
    states: dict[str, dict[str, Any]] = {}
    unknown: list[str] = []
    sources = _legacy_sources(project_root)
    for path in reversed(sources):  # pre-shard file first, so shards overwrite it
        data = load_yaml_file(path)
        if path.parent.name == SHARD_DIR.name:
            data = {path.stem: data}
        for component, state in data.items():
            if isinstance(state, dict):
                states[component] = state
            else:
                unknown.append(f"{path.name}: {component} is not a mapping")
    return states, sources, unknown


def _project_settings_data(project_root: Path) -> dict[str, Any]:
    source = next(s for s in scope_sources(project_root=project_root) if s.scope == "project")
    if source.path is None or not source.path.is_file():
        return {}
    return load_settings_text(source.path.read_text(encoding="utf-8-sig"), source.path).data


def _get(data: Any, path: Path_) -> tuple[bool, Any]:
    for part in path:
        if not isinstance(data, dict) or part not in data:
            return False, None
        data = data[part]
    return True, data


def plan_shard_migration(project_root: Path) -> MigrationPlan:
    states, sources, unknown = _load_states(project_root)
    values: dict[Path_, Any] = {}
    observations: dict[tuple[str, str], Any] = {}

    def feature_values(base: Path_, features: Any, where: str) -> None:
        if not isinstance(features, dict):
            return
        for key, entry in features.items():
            if not isinstance(entry, dict):
                unknown.append(f"{where}.features.{key}: not a mapping")
                continue
            for name, value in entry.items():
                if name in _KNOWN_FEATURE_KEYS:
                    values[(*base, "features", key, name)] = value
                else:
                    unknown.append(f"{where}.features.{key}.{name}")

    for component, state in sorted(states.items()):
        migrate_component_state_to_flat(state)
        for name in state:
            if name not in _KNOWN_COMPONENT_KEYS:
                unknown.append(f"{component}.{name}")
        feature_values(("features", component), state.get("features"), component)
        for implementation, entry in sorted((state.get("implementations") or {}).items()):
            if not isinstance(entry, dict):
                unknown.append(f"{component}.implementations.{implementation}: not a mapping")
                continue
            base = ("features", component, "implementations", implementation)
            for name, value in entry.items():
                if name not in _KNOWN_IMPLEMENTATION_KEYS:
                    unknown.append(f"{component}.implementations.{implementation}.{name}")
                elif name == "enabled" and component == PROVIDERS:
                    observations[(PROVIDERS, f"{implementation}.enabled")] = bool(value)
                elif name == "enabled":
                    values[(*base, "enabled")] = bool(value)
                elif name == "options":
                    values[(*base, "options")] = value
            feature_values(base, entry.get("features"), f"{component}.implementations.{implementation}")

    existing = _project_settings_data(project_root)
    conflicts: dict[Path_, tuple[Any, Any]] = {}
    for path, value in values.items():
        present, current = _get(existing, path)
        if present and current != value and not isinstance(value, dict):
            conflicts[path] = (current, value)
    for (component, key), value in observations.items():
        held = get_observation(project_root, component, key)
        if held is not None and held != value:
            conflicts[("observation", component, key)] = (held, value)
    return MigrationPlan(tuple(sources), values, observations, conflicts, tuple(unknown))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_dir(project_root: Path, migration_id: str) -> Path:
    return project_root / MIGRATIONS_DIR / migration_id


def _write_manifest(directory: Path, manifest: dict[str, Any]) -> None:
    atomic_write_bytes(directory / "manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())


def apply_shard_migration(project_root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Apply the plan. Raises ``ValueError`` when it has conflicts or unknown fields."""
    plan = plan_shard_migration(project_root)
    if plan.empty:
        return {"status": "nothing-to-migrate"}
    if plan.conflicts or plan.unknown:
        raise ValueError(
            f"shard migration refused: conflicts={sorted('.'.join(p) for p in plan.conflicts)} unknown={list(plan.unknown)}"
        )
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%fZ")
    directory = _manifest_dir(project_root, f"shards-{stamp}")
    backups = directory / "backup"
    backups.mkdir(parents=True, exist_ok=False)
    sources = []
    for source in plan.sources:
        relative = source.relative_to(project_root)
        target = backups / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, source.read_bytes())
        if _sha(target) != _sha(source):
            raise OSError(f"backup of {source} did not verify")
        sources.append({"path": str(relative), "sha256": _sha(source)})
    existing = _project_settings_data(project_root)
    applied = []
    for path, value in plan.values.items():
        present, before = _get(existing, path)
        applied.append({"path": list(path), "before-present": present, "before": before, "after": value})
    for (component, key), value in plan.observations.items():
        held = get_observation(project_root, component, key)
        applied.append({
            "observation": [component, key], "before-present": held is not None, "before": held, "after": value,
        })
    manifest = {
        "version": MANIFEST_VERSION, "kind": "feature-shards", "status": "prepared",
        "created": stamp, "sources": sources, "applied": applied,
    }
    _write_manifest(directory, manifest)
    if plan.values:
        write_settings_patch("project", plan.patch, project_root=project_root)
    for (component, key), value in plan.observations.items():
        record_observation(project_root, component, key, value, source="config-migrate", now=now)
    for source in plan.sources:
        source.unlink()
    manifest["status"] = "applied"
    _write_manifest(directory, manifest)
    return {"status": "applied", "manifest": str(directory / "manifest.json"), "keys": len(applied)}


def _only_removed_below(data: Any, parent: Path_, removals: list[Path_]) -> bool:
    """True when every leaf under ``parent`` is one of the keys being removed."""
    present, node = _get(data, parent)
    if not present or not isinstance(node, dict):
        return False

    def leaves(prefix: Path_, value: Any) -> list[Path_]:
        if isinstance(value, dict) and value:
            return [leaf for k, v in value.items() for leaf in leaves((*prefix, k), v)]
        return [prefix]

    return all(leaf in removals for leaf in leaves(parent, node))


def rollback_shard_migration(project_root: Path, manifest_path: Path) -> dict[str, list[str]]:
    """Undo one migration: restore each key only while it still holds the migrated value."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "feature-shards" or manifest.get("version") != MANIFEST_VERSION:
        raise ValueError("not a feature-shard migration manifest")
    if manifest["status"] == "rolled-back":
        return {"restored": [], "kept": [], "sources": []}
    current = _project_settings_data(project_root)
    restored: list[str] = []
    kept: list[str] = []
    patch: dict[str, Any] = {}
    removals: list[Path_] = []
    for entry in manifest["applied"]:
        if "observation" in entry:
            component, key = entry["observation"]
            label = f"observation {component}.{key}"
            if get_observation(project_root, component, key) != entry["after"]:
                kept.append(label)
            elif entry["before-present"]:
                record_observation(project_root, component, key, entry["before"], source="config-migrate-rollback")
                restored.append(label)
            else:
                clear_observation(project_root, component, key)
                restored.append(label)
            continue
        path = tuple(entry["path"])
        present, value = _get(current, path)
        if not present or value != entry["after"]:
            kept.append(".".join(path))
            continue
        restored.append(".".join(path))
        if entry["before-present"]:
            node = patch
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = entry["before"]
        else:
            removals.append(path)
    for path in removals:
        # Delete the key, and with it every ancestor that the deletions leave empty.
        cut = path
        while len(cut) > 1 and _only_removed_below(current, cut[:-1], removals):
            cut = cut[:-1]
        node = patch
        for part in cut[:-1]:
            node = node.setdefault(part, {})
        node[cut[-1]] = None
    if patch:
        write_settings_patch("project", patch, project_root=project_root)
    backups = manifest_path.parent / "backup"
    sources: list[str] = []
    for entry in manifest["sources"]:
        target = project_root / entry["path"]
        backup = backups / entry["path"]
        if target.exists():
            if _sha(target) != entry["sha256"]:
                kept.append(f"source {entry['path']} exists and differs")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, backup.read_bytes())
        sources.append(entry["path"])
    manifest["status"] = "rolled-back"
    _write_manifest(manifest_path.parent, manifest)
    return {"restored": restored, "kept": kept, "sources": sources}


__all__ = [
    "MIGRATIONS_DIR", "MigrationPlan", "apply_shard_migration", "plan_shard_migration",
    "rollback_shard_migration",
]
