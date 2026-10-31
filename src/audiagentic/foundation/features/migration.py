"""Move implementation ``enabled`` flags out of the feature-state shards, with a rollback.

An implementation's ``enabled`` is lifecycle state (what enable, disable and reconciliation applied
on this host), so it belongs in the observation store, not in a configuration-side shard.
``plan_enabled_migration`` lists the flags still sitting in shards; ``apply_enabled_migration``
stages verified backups of those shards, writes a manifest, records the observations and rewrites
each shard without the flag; ``rollback_enabled_migration`` restores a shard only while it is
unchanged since the migration and removes only observations that still hold the migrated value.
A flag that disagrees with an existing observation is a conflict and refuses the migration.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import atomic_write_bytes, load_yaml_file, save_yaml_file
from audiagentic.foundation.paths.names import PROJECT_MARKER_NAME

from .observations import clear_observation, get_observation, record_observation
from .state import ENABLED_PREFIX, SHARD_DIR

MIGRATIONS_DIR = Path(PROJECT_MARKER_NAME) / "state" / "migrations"
MANIFEST_VERSION = 2
MANIFEST_KIND = "enabled-observations"


@dataclass(frozen=True)
class MigrationPlan:
    shards: tuple[Path, ...]
    flags: dict[tuple[str, str], bool]  # (component, implementation) -> enabled
    conflicts: dict[tuple[str, str], tuple[bool, bool]] = field(default_factory=dict)  # -> (observed, shard)

    @property
    def empty(self) -> bool:
        return not self.flags


def plan_enabled_migration(project_root: Path) -> MigrationPlan:
    directory = project_root / SHARD_DIR
    shards: list[Path] = []
    flags: dict[tuple[str, str], bool] = {}
    for path in sorted(directory.glob("*.yaml")) if directory.is_dir() else []:
        data = load_yaml_file(path)
        found = False
        for implementation, entry in (data.get("implementations") or {}).items():
            if isinstance(entry, dict) and "enabled" in entry:
                flags[(path.stem, implementation)] = bool(entry["enabled"])
                found = True
        if found:
            shards.append(path)
    conflicts = {}
    for (component, implementation), value in flags.items():
        held = get_observation(project_root, component, ENABLED_PREFIX + implementation)
        if held is not None and held is not value:
            conflicts[(component, implementation)] = (held, value)
    return MigrationPlan(tuple(shards), flags, conflicts)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(directory: Path, manifest: dict[str, Any]) -> None:
    atomic_write_bytes(directory / "manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())


def apply_enabled_migration(project_root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Apply the plan. Raises ``ValueError`` on a conflict, touching nothing."""
    plan = plan_enabled_migration(project_root)
    if plan.empty:
        return {"status": "nothing-to-migrate"}
    if plan.conflicts:
        raise ValueError(f"enabled migration refused: conflicts={sorted(plan.conflicts)}")
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%fZ")
    directory = project_root / MIGRATIONS_DIR / f"enabled-{stamp}"
    backups = directory / "backup"
    backups.mkdir(parents=True, exist_ok=False)
    shards = []
    for shard in plan.shards:
        relative = shard.relative_to(project_root)
        target = backups / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, shard.read_bytes())
        if _sha(target) != _sha(shard):
            raise OSError(f"backup of {shard} did not verify")
        shards.append({"path": str(relative), "sha256": _sha(shard)})
    manifest = {
        "version": MANIFEST_VERSION, "kind": MANIFEST_KIND, "status": "prepared", "created": stamp,
        "shards": shards,
        "flags": [{"component": c, "implementation": i, "value": v} for (c, i), v in sorted(plan.flags.items())],
    }
    _write_manifest(directory, manifest)
    for (component, implementation), value in plan.flags.items():
        record_observation(
            project_root, component, ENABLED_PREFIX + implementation, value, source="config-migrate", now=now,
        )
    for shard in plan.shards:
        data = load_yaml_file(shard)
        for entry in data["implementations"].values():
            if isinstance(entry, dict):
                entry.pop("enabled", None)
        save_yaml_file(shard, data, sort_keys=True, atomic=True)
        manifest["shards"][plan.shards.index(shard)]["migrated-sha256"] = _sha(shard)
    manifest["status"] = "applied"
    _write_manifest(directory, manifest)
    return {"status": "applied", "manifest": str(directory / "manifest.json"), "flags": len(plan.flags)}


def rollback_enabled_migration(project_root: Path, manifest_path: Path) -> dict[str, list[str]]:
    """Undo one migration; whatever changed since is kept and reported."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != MANIFEST_KIND or manifest.get("version") != MANIFEST_VERSION:
        raise ValueError("not an enabled-observation migration manifest")
    if manifest["status"] == "rolled-back":
        return {"restored": [], "kept": []}
    restored: list[str] = []
    kept: list[str] = []
    backups = manifest_path.parent / "backup"
    restorable: set[str] = set()
    for entry in manifest["shards"]:
        target = project_root / entry["path"]
        if not target.is_file() or _sha(target) == entry.get("migrated-sha256"):
            restorable.add(Path(entry["path"]).stem)
        else:
            kept.append(f"{entry['path']} (changed since the migration)")
    for entry in manifest["flags"]:
        key = ENABLED_PREFIX + entry["implementation"]
        label = f"{entry['component']}.{entry['implementation']}"
        if entry["component"] not in restorable:
            kept.append(f"{label} (its shard was kept)")
        elif get_observation(project_root, entry["component"], key) is entry["value"]:
            clear_observation(project_root, entry["component"], key)
            restored.append(label)
        else:
            kept.append(f"{label} (observation changed since the migration)")
    for entry in manifest["shards"]:
        if Path(entry["path"]).stem in restorable:
            atomic_write_bytes(project_root / entry["path"], (backups / entry["path"]).read_bytes())
            restored.append(entry["path"])
    manifest["status"] = "rolled-back"
    _write_manifest(manifest_path.parent, manifest)
    return {"restored": restored, "kept": kept}


__all__ = [
    "MIGRATIONS_DIR", "MigrationPlan", "apply_enabled_migration", "plan_enabled_migration",
    "rollback_enabled_migration",
]
