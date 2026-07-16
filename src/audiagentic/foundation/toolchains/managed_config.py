"""Domain-neutral managed configuration contracts and ownership registry.

Also hosts the shared reconcile/reload core (MO06): ``sync_managed_config``
and ``reload_managed_config`` are the domain-neutral extraction of
``components/providers/services/mcp.py``'s original ``_sync_managed_entries``/
``reload_provider_mcp`` bodies, generalized to bind ``fragments.py`` against
any :class:`ManagedConfigSpec` + :class:`ManagedFragmentRegistry` pair — MCP,
LSP, and future managed-config kinds share one implementation instead of each
cloning the reconcile loop.

NON-GOAL (OU01 step 6): config-write path is NEVER redacted. Provider config
legitimately CARRIES secrets: mcp_config env blocks hold API keys and writing
them is the entire feature. Config is the SOURCE of the secret, not a leak of
it. Redacting there breaks MCP auth. Protection for config is ownership/scoping
and gitignore, not redaction.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.toolchains.fragments import FragmentStore, reconcile_fragments

_config_error = make_error_factory("VAL", "MCFG", "managed-config")
_registry_error = make_error_factory("CON", "MCFG", "managed-config")


@dataclass(frozen=True)
class ManagedConfigSpec:
    """Format adapter contract for named managed entries."""

    config_path: str | Callable[[Path | None], Path]
    reader: Callable[[Path], dict[str, Any]]
    writer: Callable[[Path, dict[str, Any]], None]
    remover: Callable[[Path, str], bool]
    format: str = ""
    refresh_mode: str = "none"
    reload_fn: Callable[[Path], dict[str, Any]] | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)


def resolve_managed_config_path(spec: ManagedConfigSpec, project_root: Path | None) -> Path:
    """Resolve callable, home-relative, absolute, and project-relative paths."""
    raw = spec.config_path(project_root) if callable(spec.config_path) else spec.config_path
    if not isinstance(raw, (str, Path)):
        raise _config_error(1, "managed config path must resolve to str or Path")
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    if project_root is None:
        raise _config_error(1, "relative managed config path requires a project root")
    return project_root / path


def apply_managed_config_write(spec: ManagedConfigSpec, path: Path, entries: dict[str, Any]) -> None:
    """Sanctioned call site for a spec's writer outside the fragment core.

    Kinds without per-entry ownership tracking (e.g. LSP language-server sync,
    which upserts the whole desired language set each time with no managed_id
    registry) call this instead of ``spec.writer`` directly, so exactly two
    places in the codebase ever touch ``.writer``/``.remover``: this module
    and the fragment-based ``sync_managed_config`` above.
    """
    spec.writer(path, entries)


def apply_managed_config_remove(spec: ManagedConfigSpec, path: Path, name: str) -> bool:
    """Sanctioned call site for a spec's remover outside the fragment core."""
    return spec.remover(path, name)


class ManagedFragmentRegistry:
    """Atomic ownership registry for opaque named fragments."""

    def __init__(
        self,
        project_root: Path,
        filename: str,
        *,
        top_level_key: str = "owners",
        contract_version: str = "v1",
    ) -> None:
        self._path = project_root / ".audiagentic" / "runtime" / "providers" / filename
        self._top_level_key = top_level_key
        self._contract_version = contract_version

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise _registry_error(1, "managed fragment registry is unreadable") from exc
        if not isinstance(payload, dict) or payload.get("contract-version") != self._contract_version:
            raise _registry_error(1, "managed fragment registry has an invalid contract")
        owners = payload.get(self._top_level_key)
        if not isinstance(owners, dict):
            raise _registry_error(1, "managed fragment registry has an invalid ownership root")
        result: dict[str, dict[str, str]] = {}
        for scope, entries in owners.items():
            if not isinstance(scope, str) or not isinstance(entries, dict):
                raise _registry_error(1, "managed fragment registry has an invalid ownership entry")
            if not all(isinstance(key, str) and isinstance(value, str) for key, value in entries.items()):
                raise _registry_error(1, "managed fragment registry contains a non-string ownership entry")
            result[scope] = dict(entries)
        return result

    def save(self, owners: dict[str, dict[str, str]]) -> None:
        if not all(
            isinstance(scope, str)
            and isinstance(entries, dict)
            and all(isinstance(key, str) and isinstance(value, str) for key, value in entries.items())
            for scope, entries in owners.items()
        ):
            raise _config_error(1, "managed fragment ownership must be string mappings")
        atomic_write_json(self._path, {
            "contract-version": self._contract_version,
            self._top_level_key: owners,
        })


@dataclass
class ManagedSyncResult:
    """Structured outcome of :func:`sync_managed_config`."""

    owner_scope: str
    ok: bool
    config_path: str
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    collisions: list[dict[str, str]] = field(default_factory=list)
    reload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider_id": self.owner_scope,
            "ok": self.ok,
            "config_path": self.config_path,
            "updated": self.updated,
            "removed": self.removed,
            "collisions": self.collisions,
        }
        # Merge reload info WITHOUT letting its "ok" mask a sync failure: a
        # collision (sync ok=False) must never be reported as ok=True just
        # because the subsequent reload succeeded. Overall ok = sync AND reload.
        reload_info = dict(self.reload)
        reload_ok = reload_info.pop("ok", True)
        result.update(reload_info)
        result["ok"] = self.ok and bool(reload_ok)
        return result


def sync_managed_config(
    spec: ManagedConfigSpec,
    project_root: Path,
    owner_scope: str,
    desired_entries: dict[str, tuple[str, Any]],
    *,
    registry: ManagedFragmentRegistry,
    managed_ids: set[str] | None = None,
) -> ManagedSyncResult:
    """Reconcile *spec*'s config toward *desired_entries* for *owner_scope*.

    Thin binding over :func:`~audiagentic.foundation.toolchains.fragments.reconcile_fragments`:
    the store is the spec's reader/writer/remover trio, the ownership registry
    is the injected :class:`ManagedFragmentRegistry`. Reloads via
    :func:`reload_managed_config` only when something actually changed.
    """
    config_path = resolve_managed_config_path(spec, project_root)
    store = FragmentStore(read=spec.reader, write=spec.writer, remove=spec.remover)
    outcome = reconcile_fragments(
        store,
        config_path,
        owner_scope,
        desired_entries,
        registry_load=registry.load,
        registry_save=registry.save,
        managed_ids=managed_ids,
    )

    result = ManagedSyncResult(
        owner_scope=owner_scope,
        ok=outcome.ok,
        config_path=str(config_path),
        updated=outcome.updated,
        removed=outcome.removed,
        collisions=outcome.collisions,
    )
    result.reload = (
        reload_managed_config(spec, project_root, display_name=owner_scope)
        if outcome.changed
        else {"auto_refreshed": True, "method": "no-op"}
    )
    return result


def reload_managed_config(
    spec: ManagedConfigSpec,
    project_root: Path,
    *,
    display_name: str,
) -> dict[str, Any]:
    """Signal or reload a provider after *spec*'s config has changed.

    ``file-watch`` kinds auto-reload on file change — nothing extra needed.
    ``restart-required`` kinds call ``reload_fn`` if defined, otherwise inform
    only. ``refresh_mode="none"`` (the default; e.g. LSP) reports
    auto-refreshed with no reload concept, matching pre-MO06 LSP behavior
    (LSP never signaled reload).
    """
    if spec.refresh_mode == "none":
        return {"ok": True, "auto_refreshed": True, "method": "no-reload-concept"}

    if spec.refresh_mode == "file-watch":
        return {"ok": True, "auto_refreshed": True, "method": "file-watch"}

    if spec.reload_fn is not None:
        try:
            fn_result = spec.reload_fn(project_root)
        except Exception as exc:  # noqa: BLE001 — third-party reload call, never fatal
            return {"ok": False, "method": "reload-fn", "error": str(exc)}
        return {"ok": True, "auto_refreshed": True, "method": "reload-fn", **fn_result}

    return {
        "ok": True,
        "auto_refreshed": False,
        "method": "restart-required",
        "action_needed": f"restart {display_name} to apply config changes",
    }


#: Capability flag recorded in :attr:`ManagedConfigSpec.capabilities` when a
#: kind's format can express url-form (remote) entries — MCP-specific
#: semantics preserved through the generic capability set rather than a
#: named field (keeps the spec itself domain-neutral). Absence means
#: stdio-shaped entries only.
REMOTE_CAPABILITY = "remote"
