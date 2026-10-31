"""Move legacy configuration files into settings, with a rollback.

``plan_provider_config_migration`` reads every legacy file it knows (provider options, registry and
policy, model sources, harness, logging, event config and triggers, prompt syntax, the machine gpt-auto
override and the per-component feature-state shards) and returns the settings it implies, what it
would write as local observations, and anything that blocks it (a different existing value, or a legacy
key with no home). ``apply_provider_config_migration`` stages verified backups, writes a manifest, applies
the settings patches and observations, and only then removes the sources. ``rollback_...`` restores a key
only while it still holds the migrated value, so later edits survive.

The feature-state shards were gitignored per-host files: their option and feature choices become the
``features`` section of the *user-project* scope (one person's untracked choices for one project), and an
implementation's ``enabled`` flag, which is lifecycle state, becomes a local observation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import atomic_write_bytes, load_yaml_file
from audiagentic.foundation.paths.names import PROJECT_MARKER_NAME

from .observations import clear_observation, get_observation, record_observation
from .state import ENABLED_PREFIX

MIGRATIONS_DIR = Path(PROJECT_MARKER_NAME) / "state" / "migrations"
MANIFEST_VERSION = 2
FEATURE_SHARDS_DIR = Path(PROJECT_MARKER_NAME) / "config" / "runtime" / "features"
_SHARD_KEYS = {"options", "features", "implementations"}
_SHARD_IMPLEMENTATION_KEYS = {"enabled", "options", "features"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(directory: Path, manifest: dict[str, Any]) -> None:
    atomic_write_bytes(directory / "manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())


PROVIDER_CONFIG_KIND = "provider-config"
_PROVIDER_FILE_DROP = ("install-mode", "access-mode", "enabled")
PROVIDER_FILES_DIR = Path(PROJECT_MARKER_NAME) / "config" / "providers"
PROVIDER_REGISTRY = Path(PROJECT_MARKER_NAME) / "config" / "runtime" / "providers.yaml"
PROVIDER_POLICY = Path(PROJECT_MARKER_NAME) / "config" / "provider-policy.yaml"
PROJECT_MODEL_SOURCES = Path(PROJECT_MARKER_NAME) / "config" / "model-sources.yaml"
HARNESS_FILES_DIR = Path(PROJECT_MARKER_NAME) / "config" / "harness"
LOGGING_FILES_DIR = Path(PROJECT_MARKER_NAME) / "config" / "foundation"
PROJECT_FILE = Path(PROJECT_MARKER_NAME) / "config" / "project.yaml"
EVENT_CONFIG = Path(PROJECT_MARKER_NAME) / "event" / "config.yaml"
EVENT_TRIGGERS = Path(PROJECT_MARKER_NAME) / "config" / "agent-jobs" / "event-triggers.yaml"
PROMPT_SYNTAX = Path(PROJECT_MARKER_NAME) / "config" / "execution" / "prompt-syntax.yaml"
DECIDED_KEY = "reconciliation.decided"
_HARNESS_AG_KEYS = {"endpoint", "smoke", "mcp"}

# A settings key is (scope, section, ...): the scope names the settings file it lives in.
SettingsPath = tuple[str, ...]


@dataclass(frozen=True)
class ProviderConfigPlan:
    sources: tuple[Path, ...]
    values: dict[SettingsPath, Any]
    decided: list[str] | None
    conflicts: dict[tuple[str, ...], tuple[Any, Any]] = field(default_factory=dict)  # path -> (existing, planned)
    unknown: tuple[str, ...] = ()
    observations: dict[tuple[str, str], Any] = field(default_factory=dict)  # (component, key) -> value  # legacy keys with no settings home; they refuse the migration

    def patch(self, scope: str) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        for path, value in self.values.items():
            if path[0] != scope:
                continue
            node = patch
            for part in path[1:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = value
        return patch

    @property
    def empty(self) -> bool:
        return not self.sources


def _scope_documents(project_root: Path) -> dict[str, dict[str, Any]]:
    from audiagentic.foundation.config.writer import read_scope_settings

    return {
        "project": read_scope_settings("project", project_root=project_root),
        "user": read_scope_settings("user"),
        "user-project": read_scope_settings("user-project", project_root=project_root),
    }


def _lookup(data: Any, path: SettingsPath) -> tuple[bool, Any]:
    for part in path:
        if not isinstance(data, dict) or part not in data:
            return False, None
        data = data[part]
    return True, data


def _leaves(prefix: SettingsPath, value: Any) -> dict[SettingsPath, Any]:
    if isinstance(value, dict) and value:
        found: dict[SettingsPath, Any] = {}
        for key, child in value.items():
            found.update(_leaves((*prefix, str(key)), child))
        return found
    return {prefix: value}


def _user_harness_dir() -> Path:
    from audiagentic.foundation.paths.home import audiagentic_home

    return audiagentic_home() / "config" / "harness"


def _harness_values(scope: str, directory: Path, unknown: list[str]) -> tuple[list[Path], dict[SettingsPath, Any]]:
    """Legacy ag.yaml and pi.yaml in one directory, as keys of the ``harness`` section."""
    files: list[Path] = []
    values: dict[SettingsPath, Any] = {}
    ag = directory / "ag.yaml"
    if ag.is_file():
        files.append(ag)
        data = load_yaml_file(ag)
        for key, value in data.items():
            if key == "harness" and isinstance(value, dict):
                for name, item in value.items():
                    if name in ("order", "type"):
                        values[(scope, "harness", name)] = item
                    else:
                        unknown.append(f"{ag}: harness.{name}")
            elif key in _HARNESS_AG_KEYS:
                values.update(_leaves((scope, "harness", key), value))
            else:
                unknown.append(f"{ag}: {key}")
    pi = directory / "pi.yaml"
    if pi.is_file():
        files.append(pi)
        values.update(_leaves((scope, "harness", "pi"), load_yaml_file(pi)))
    return files, values


def _logging_values(
    files: list[tuple[str, Path]], unknown: list[str],
) -> tuple[list[Path], dict[SettingsPath, Any]]:
    """Legacy logging files as keys of the ``logging`` section (``exclusive_local`` has no equivalent)."""
    found: list[Path] = []
    values: dict[SettingsPath, Any] = {}
    for scope, file in files:
        if not file.is_file():
            continue
        found.append(file)
        data = load_yaml_file(file)
        for key, value in data.items():
            if key != "logging" or not isinstance(value, dict):
                unknown.append(f"{file}: {key}")
                continue
            for path, leaf in _leaves((scope, "logging"), value).items():
                if leaf is None:
                    continue  # a null meant "unset": nothing to carry over
                if path in values and values[path] != leaf:
                    unknown.append(f"{file}: {'.'.join(path[1:])} also set differently in another logging file")
                values[path] = leaf
    return found, values


def _project_section_files(project_root: Path, unknown: list[str]) -> tuple[list[Path], dict[SettingsPath, Any]]:
    """Single-file project readers: event layer config, event triggers and the prompt-syntax overlay."""
    found: list[Path] = []
    values: dict[SettingsPath, Any] = {}
    events = project_root / EVENT_CONFIG
    if events.is_file():
        found.append(events)
        data = load_yaml_file(events)
        for key, value in data.items():
            if key == "runtime" and isinstance(value, dict):
                values.update(_leaves(("project", "events"), value))
            else:
                unknown.append(f"{events}: {key}")
    triggers = project_root / EVENT_TRIGGERS
    if triggers.is_file():
        found.append(triggers)
        data = load_yaml_file(triggers)
        items = data.get("triggers", data.get("event-triggers"))
        if isinstance(items, list):
            values[("project", "event-triggers")] = items
        else:
            unknown.append(f"{triggers}: no 'triggers' list")
    syntax = project_root / PROMPT_SYNTAX
    if syntax.is_file():
        found.append(syntax)
        overlay = {k: v for k, v in load_yaml_file(syntax).items() if k != "contract-version"}
        values.update(_leaves(("project", "prompt-syntax"), overlay))
    return found, values


def _machine_provider_overrides(unknown: list[str]) -> tuple[list[Path], dict[SettingsPath, Any]]:
    """Machine-level provider override files (``<home>/config/providers/<id>.yaml``) as user-scope settings."""
    from audiagentic.foundation.paths.home import global_config_dir

    directory = global_config_dir() / "providers"
    found: list[Path] = []
    values: dict[SettingsPath, Any] = {}
    for file in sorted(directory.glob("*.yaml")) if directory.is_dir() else []:
        found.append(file)
        data = load_yaml_file(file)
        settings = data["settings"] if "settings" in data else {
            k: v for k, v in data.items() if k not in _PROVIDER_FILE_DROP
        }
        if not isinstance(settings, dict):
            unknown.append(f"{file}: settings is not a mapping")
            continue
        values.update(_leaves(("user", "providers", file.stem, "settings"), settings))
    return found, values


def _feature_shard_values(
    project_root: Path, unknown: list[str],
) -> tuple[list[Path], dict[SettingsPath, Any], dict[tuple[str, str], Any]]:
    """Feature-state shards: choices to the user-project ``features`` section, ``enabled`` flags to observations."""
    directory = project_root / FEATURE_SHARDS_DIR
    found: list[Path] = []
    values: dict[SettingsPath, Any] = {}
    observations: dict[tuple[str, str], Any] = {}
    for file in sorted(directory.glob("*.yaml")) if directory.is_dir() else []:
        found.append(file)
        component = file.stem
        data = load_yaml_file(file)
        for key in data:
            if key not in _SHARD_KEYS:
                unknown.append(f"{file}: {key}")
        for key in ("options", "features"):
            if key in data:
                values.update(_leaves(("user-project", "features", component, key), data[key]))
        for implementation, entry in (data.get("implementations") or {}).items():
            if not isinstance(entry, dict):
                unknown.append(f"{file}: implementations.{implementation} is not a mapping")
                continue
            for key, value in entry.items():
                if key == "enabled":
                    observations[(component, ENABLED_PREFIX + implementation)] = bool(value)
                elif key in _SHARD_IMPLEMENTATION_KEYS:
                    values.update(_leaves(("user-project", "features", component, "implementations", implementation, key), value))
                else:
                    unknown.append(f"{file}: implementations.{implementation}.{key}")
    return found, values, observations


def _user_model_sources_file() -> Path:
    from audiagentic.foundation.paths.home import audiagentic_home

    return audiagentic_home() / "config" / "model-sources.yaml"


# Keys the project file once carried that nothing reads any more: they are dropped, not migrated.
_PROJECT_FILE_UNUSED = {
    "contract-version", "workflow-profile", "tracked-docs-root", "runtime-root", "release-strategy",
    "workflow-overrides",
}


def _project_file_values(project_root: Path, unknown: list[str]) -> tuple[list[Path], dict[SettingsPath, Any]]:
    """The legacy project file: identity, prompt-launch defaults and MCP bindings move to project settings."""
    path = project_root / PROJECT_FILE
    if not path.is_file():
        return [], {}
    values: dict[SettingsPath, Any] = {}
    for key, value in load_yaml_file(path).items():
        if key in _PROJECT_FILE_UNUSED or (key == "project-id" and not value) or (key == "project-name" and not value):
            continue
        if key == "project-id":
            values[("project", "project", "id")] = value
        elif key == "project-name":
            values[("project", "project", "name")] = value
        elif key == "prompt-launch" and isinstance(value, dict):
            values.update(_leaves(("project", "prompt-launch"), {k: v for k, v in value.items() if k != "syntax"}))
        elif key == "mcp-onboarding" and isinstance(value, dict):
            values.update(_leaves(("project", "mcp-onboarding", "bindings"), value.get("bindings") or {}))
        else:
            unknown.append(f"{path}: {key}")
    return [path], values


def plan_provider_config_migration(project_root: Path) -> ProviderConfigPlan:
    sources: list[Path] = []
    entries: dict[str, dict[str, Any]] = {}
    registry = project_root / PROVIDER_REGISTRY
    if registry.is_file():
        sources.append(registry)
        for provider_id, entry in (load_yaml_file(registry).get("providers") or {}).items():
            if isinstance(entry, dict):
                entries[provider_id] = dict(entry)
    directory = project_root / PROVIDER_FILES_DIR
    for path in sorted(directory.glob("*.yaml")) if directory.is_dir() else []:
        sources.append(path)
        entries[path.stem] = {**entries.get(path.stem, {}), **load_yaml_file(path)}
    values: dict[SettingsPath, Any] = {}
    for provider_id, entry in sorted(entries.items()):
        options = {k: v for k, v in entry.items() if k not in _PROVIDER_FILE_DROP}
        values.update(_leaves(("project", "providers", provider_id), options))
    decided: list[str] | None = None
    policy = project_root / PROVIDER_POLICY
    if policy.is_file():
        sources.append(policy)
        section = load_yaml_file(policy).get("reconciliation-policy") or {}
        if "mode" in section:
            values[("project", "reconciliation", "mode")] = section["mode"]
        if "allowed-providers" in section:
            values[("project", "reconciliation", "allowed-providers")] = sorted(set(section["allowed-providers"]))
        if "decided-providers" in section:
            decided = sorted(set(section["decided-providers"]))
    for scope, file in (("project", project_root / PROJECT_MODEL_SOURCES), ("user", _user_model_sources_file())):
        if file.is_file():
            sources.append(file)
            for source_id, source in (load_yaml_file(file).get("sources") or {}).items():
                values.update(_leaves((scope, "model-sources", str(source_id)), source))
    unknown: list[str] = []
    for scope, directory in (("project", project_root / HARNESS_FILES_DIR), ("user", _user_harness_dir())):
        files, harness_values = _harness_values(scope, directory, unknown)
        sources.extend(files)
        values.update(harness_values)
    from audiagentic.foundation.paths.home import audiagentic_home

    # The machine-local file is per host, so it goes to the user scope with the user-global one.
    logging_files, logging_values = _logging_values(
        [
            ("project", project_root / LOGGING_FILES_DIR / "logging.yaml"),
            ("user", project_root / LOGGING_FILES_DIR / "logging.local.yaml"),
            ("user", audiagentic_home() / "config" / "foundation" / "logging.yaml"),
        ],
        unknown,
    )
    sources.extend(logging_files)
    values.update(logging_values)
    machine_files, machine_values = _machine_provider_overrides(unknown)
    sources.extend(machine_files)
    values.update(machine_values)
    section_files, section_values = _project_section_files(project_root, unknown)
    sources.extend(section_files)
    values.update(section_values)
    project_files, project_values = _project_file_values(project_root, unknown)
    sources.extend(project_files)
    values.update(project_values)
    shard_files, shard_values, shard_observations = _feature_shard_values(project_root, unknown)
    sources.extend(shard_files)
    values.update(shard_values)
    documents = _scope_documents(project_root)
    conflicts: dict[SettingsPath, tuple[Any, Any]] = {}
    for path, value in values.items():
        present, current = _lookup(documents[path[0]], path[1:])
        if present and current != value:
            conflicts[path] = (current, value)
    for (component, key), value in shard_observations.items():
        held = get_observation(project_root, component, key)
        if held is not None and held is not value:
            conflicts[("observation", component, key)] = (held, value)
    return ProviderConfigPlan(tuple(sources), values, decided, conflicts, tuple(unknown), shard_observations)


def _backup_name(index: int, source: Path) -> str:
    return f"{index:03d}-{source.name}"


def apply_provider_config_migration(project_root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    from audiagentic.foundation.config.writer import write_settings_patch

    plan = plan_provider_config_migration(project_root)
    if plan.empty:
        return {"status": "nothing-to-migrate"}
    if plan.conflicts or plan.unknown:
        raise ValueError(
            "legacy configuration migration refused: conflicts=" + str(sorted(".".join(p) for p in plan.conflicts))
            + f" unknown={list(plan.unknown)}"
        )
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%fZ")
    directory = project_root / MIGRATIONS_DIR / f"provider-config-{stamp}"
    backups = directory / "backup"
    backups.mkdir(parents=True, exist_ok=False)
    sources = []
    for index, source in enumerate(plan.sources):
        name = _backup_name(index, source)
        atomic_write_bytes(backups / name, source.read_bytes())
        if _sha(backups / name) != _sha(source):
            raise OSError(f"backup of {source} did not verify")
        sources.append({"path": str(source), "sha256": _sha(source), "backup": name})
    documents = _scope_documents(project_root)
    applied = []
    for path, value in plan.values.items():
        present, before = _lookup(documents[path[0]], path[1:])
        applied.append({"path": list(path), "before-present": present, "before": before, "after": value})
    held = get_observation(project_root, "providers", DECIDED_KEY)
    observation_changes = [
        {"component": c, "key": k, "before": get_observation(project_root, c, k), "after": v}
        for (c, k), v in sorted(plan.observations.items())
    ]
    manifest = {
        "version": MANIFEST_VERSION, "kind": PROVIDER_CONFIG_KIND, "status": "prepared", "created": stamp,
        "sources": sources, "applied": applied,
        "decided": {"before": held, "after": plan.decided} if plan.decided is not None else None,
        "observations": observation_changes,
    }
    _write_manifest(directory, manifest)
    for scope in ("project", "user", "user-project"):
        patch = plan.patch(scope)
        if patch:
            write_settings_patch(scope, patch, project_root=project_root)
    if plan.decided is not None:
        record_observation(project_root, "providers", DECIDED_KEY, plan.decided, source="config-migrate", now=now)
    for (component, key), value in plan.observations.items():
        record_observation(project_root, component, key, value, source="config-migrate", now=now)
    for source in plan.sources:
        source.unlink()
    manifest["status"] = "applied"
    _write_manifest(directory, manifest)
    return {"status": "applied", "manifest": str(directory / "manifest.json"), "keys": len(applied)}


def rollback_provider_config_migration(project_root: Path, manifest_path: Path) -> dict[str, list[str]]:
    """Restore each key only while it still holds the migrated value; later edits are kept."""
    from audiagentic.foundation.config.writer import write_settings_patch

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != PROVIDER_CONFIG_KIND or manifest.get("version") != MANIFEST_VERSION:
        raise ValueError("not a legacy-configuration migration manifest")
    if manifest["status"] == "rolled-back":
        return {"restored": [], "kept": []}
    documents = _scope_documents(project_root)
    restored: list[str] = []
    kept: list[str] = []
    patches: dict[str, dict[str, Any]] = {"project": {}, "user": {}, "user-project": {}}
    removals: dict[str, list[SettingsPath]] = {"project": [], "user": [], "user-project": []}
    for entry in manifest["applied"]:
        scope, path = entry["path"][0], tuple(entry["path"][1:])
        present, value = _lookup(documents[scope], path)
        label = ".".join(entry["path"])
        if not present or value != entry["after"]:
            kept.append(label)
            continue
        restored.append(label)
        if entry["before-present"]:
            node = patches[scope]
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = entry["before"]
        else:
            removals[scope].append(path)
    for scope, paths in removals.items():
        for path in paths:
            cut = path
            while len(cut) > 1 and _only_removed_below(documents[scope], cut[:-1], paths):
                cut = cut[:-1]
            node = patches[scope]
            for part in cut[:-1]:
                node = node.setdefault(part, {})
            node[cut[-1]] = None
    for scope, patch in patches.items():
        if patch:
            write_settings_patch(scope, patch, project_root=project_root)
    decided = manifest.get("decided")
    if decided is not None:
        if get_observation(project_root, "providers", DECIDED_KEY) == decided["after"]:
            if decided["before"] is None:
                clear_observation(project_root, "providers", DECIDED_KEY)
            else:
                record_observation(project_root, "providers", DECIDED_KEY, decided["before"], source="config-migrate")
            restored.append("reconciliation.decided")
        else:
            kept.append("reconciliation.decided")
    for change in manifest.get("observations", []):
        label = f"observation {change['component']}.{change['key']}"
        if get_observation(project_root, change["component"], change["key"]) is not change["after"]:
            kept.append(label)
        elif change["before"] is None:
            clear_observation(project_root, change["component"], change["key"])
            restored.append(label)
        else:
            record_observation(
                project_root, change["component"], change["key"], change["before"], source="config-migrate-rollback",
            )
            restored.append(label)
    backups = manifest_path.parent / "backup"
    for entry in manifest["sources"]:
        target = Path(entry["path"])
        if target.exists():
            kept.append(f"{entry['path']} (exists; not overwritten)")
            continue
        atomic_write_bytes(target, (backups / entry["backup"]).read_bytes())
        restored.append(entry["path"])
    manifest["status"] = "rolled-back"
    _write_manifest(manifest_path.parent, manifest)
    return {"restored": restored, "kept": kept}


def _only_removed_below(data: Any, parent: SettingsPath, removals: list[SettingsPath]) -> bool:
    present, node = _lookup(data, parent)
    if not present or not isinstance(node, dict):
        return False
    return all(leaf in removals for leaf in _leaves(parent, node))


__all__ = [
    "FEATURE_SHARDS_DIR", "MIGRATIONS_DIR", "PROVIDER_CONFIG_KIND", "ProviderConfigPlan",
    "apply_provider_config_migration", "plan_provider_config_migration", "rollback_provider_config_migration",
]
