"""Machine-scoped known-projects registry for gpt-auto config drift detection (GP26).

The gateway SERVICE is machine-scoped (one shared process serving every project
on the machine), while provider SETTINGS (dom-signals/evidence-policies/turn
timers in .audiagentic/config/providers/*.yaml) are project-local. GP09 fixed
the underlying schema-drift hazard (GP20 three-tier loader, GP21 v1->v2
migration); this registry is the remaining prevention/observability layer: it
answers which projects the machine gateway should inspect, when they were last
seen/checked, and whether the authoritative loader currently accepts each one.

The registry is ADVISORY. It is diagnostic/cache information, never an
authorization gate and never a gateway availability dependency: a project found
incompatible at startup is still revalidated at actual use time, and a corrupt
or unreadable registry must not prevent gateway startup.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

REGISTRY_SCHEMA_VERSION = 1

ConfigStatus = Literal["unknown", "compatible", "incompatible"]

_VALID_STATUSES: tuple[ConfigStatus, ...] = ("unknown", "compatible", "incompatible")


@dataclass(frozen=True, slots=True)
class KnownProject:
    project_root: Path
    last_seen_at: datetime
    last_config_check_at: datetime | None
    config_status: ConfigStatus
    config_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class KnownProjectsRegistry:
    schema_version: int
    projects: tuple[KnownProject, ...]

    def get(self, project_root: Path) -> KnownProject | None:
        key = _canonical_root(project_root)
        for project in self.projects:
            if _canonical_root(project.project_root) == key:
                return project
        return None


@dataclass(frozen=True, slots=True)
class ProjectConfigScanFailure:
    project_root: Path
    error_code: str
    message: str


@dataclass(frozen=True, slots=True)
class ProjectConfigScanResult:
    checked: int
    compatible: int
    incompatible: tuple[ProjectConfigScanFailure, ...]

    @property
    def failed(self) -> int:
        return len(self.incompatible)


def _canonical_root(project_root: Path) -> Path:
    """Normalize a project root for registry keying (absolute, resolved)."""
    return Path(os.path.abspath(str(project_root)))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _from_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_raw(path: Path) -> dict | None:
    """Read and parse the registry file, tolerating absence and corruption.

    Returns None when the file must be treated as absent or unreadable
    (corrupt JSON, wrong schema version). Never raises.
    """
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        logger.warning(
            "known-projects registry is unreadable; starting with an empty registry "
            "(advisory, non-fatal)",
            extra={"path": str(path), "error": str(exc)},
        )
        return None
    if not isinstance(raw, dict):
        logger.warning(
            "known-projects registry is not an object; starting with an empty registry "
            "(advisory, non-fatal)",
            extra={"path": str(path)},
        )
        return None
    schema_version = raw.get("schema-version")
    if schema_version != REGISTRY_SCHEMA_VERSION:
        logger.warning(
            "known-projects registry uses unsupported schema version %r; "
            "using it read-only for this boot (advisory, non-fatal)",
            schema_version,
            extra={"path": str(path)},
        )
        return None
    return raw


def load_known_projects(path: Path) -> KnownProjectsRegistry:
    """Load the registry, tolerating a missing, corrupt, or future-schema file.

    A corrupt or unsupported-schema registry yields an empty in-memory registry
    for this boot and is never silently overwritten.
    """
    raw = _load_raw(path)
    if raw is None:
        return KnownProjectsRegistry(REGISTRY_SCHEMA_VERSION, ())

    projects_raw = raw.get("projects")
    if not isinstance(projects_raw, dict):
        return KnownProjectsRegistry(REGISTRY_SCHEMA_VERSION, ())

    projects: list[KnownProject] = []
    for key, entry in projects_raw.items():
        if not isinstance(entry, dict):
            continue
        project_root_raw = entry.get("project-root")
        if not isinstance(project_root_raw, str) or not project_root_raw:
            continue
        project_root = _canonical_root(Path(project_root_raw))
        if str(project_root) != str(key):
            # Normalize on the key's behalf; a drift between key and value is
            # not gateway corruption -- prefer the value but keep both aligned.
            key = str(project_root)
        status = entry.get("config-status", "unknown")
        if status not in _VALID_STATUSES:
            status = "unknown"
        error_code = entry.get("config-error-code")
        projects.append(
            KnownProject(
                project_root=project_root,
                last_seen_at=_from_iso(entry.get("last-seen-at")) or _utc_now(),
                last_config_check_at=_from_iso(entry.get("last-config-check-at")),
                config_status=status,  # type: ignore[arg-type]
                config_error_code=error_code if isinstance(error_code, str) else None,
            )
        )

    projects.sort(key=lambda p: str(p.project_root))
    return KnownProjectsRegistry(REGISTRY_SCHEMA_VERSION, tuple(projects))


def _serialize(registry: KnownProjectsRegistry) -> dict:
    return {
        "schema-version": registry.schema_version,
        "projects": {
            str(project.project_root): {
                "project-root": str(project.project_root),
                "last-seen-at": _to_iso(project.last_seen_at),
                "last-config-check-at": _to_iso(project.last_config_check_at),
                "config-status": project.config_status,
                "config-error-code": project.config_error_code,
            }
            for project in registry.projects
        },
    }


def _atomic_write(path: Path, payload: dict) -> bool:
    """Atomically persist the registry (temp + fsync + os.replace).

    Returns False (and logs) on failure -- the registry is an observability
    cache and must never turn into a production outage.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "could not create known-projects registry directory (non-fatal)",
            extra={"path": str(path), "error": str(exc)},
        )
        return False
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError as exc:
        logger.warning(
            "could not write known-projects registry (non-fatal)",
            extra={"path": str(path), "error": str(exc)},
        )
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def record_known_project(
    path: Path,
    *,
    project_root: Path,
    checked_at: datetime | None = None,
    config_status: ConfigStatus = "unknown",
    config_error_code: str | None = None,
) -> bool:
    """Merge one project's entry into the registry and persist atomically.

    Merges the latest on-disk registry immediately before replacement so
    concurrent project activity cannot casually erase another project's entry.
    Returns True when persisted (or the on-disk registry is unsupported and
    intentionally left untouched).
    """
    if config_status not in _VALID_STATUSES:
        raise ValueError(f"config_status must be one of {_VALID_STATUSES}, got {config_status!r}")
    canonical = _canonical_root(project_root)
    now = checked_at or _utc_now()

    latest = load_known_projects(path)
    if latest.schema_version != REGISTRY_SCHEMA_VERSION:
        # Future/unknown schema: read-only for this boot, never overwrite.
        return True

    existing = latest.get(canonical)
    project = KnownProject(
        project_root=canonical,
        last_seen_at=existing.last_seen_at if existing else now,
        last_config_check_at=checked_at,
        config_status=config_status,
        config_error_code=config_error_code,
    )
    merged = {
        str(entry.project_root): entry
        for entry in latest.projects
        if str(entry.project_root) != str(canonical)
    }
    merged[str(canonical)] = project
    registry = KnownProjectsRegistry(
        REGISTRY_SCHEMA_VERSION, tuple(sorted(merged.values(), key=lambda p: str(p.project_root)))
    )
    return _atomic_write(path, _serialize(registry))


def scan_known_gpt_auto_projects(
    path: Path,
    *,
    check_project: Callable[[Path], None],
    now: datetime | None = None,
) -> ProjectConfigScanResult:
    """Revalidate every known project against the authoritative config loader.

    *check_project* is the gpt-auto validation callable; it must raise (with a
    machine-readable error code) for an incompatible project and return without
    raising for a compatible one. Incompatible projects are recorded as such in
    the registry but never fail the scan or the gateway itself; missing project
    directories are marked stale rather than treated as corruption.
    """
    now = now or _utc_now()
    registry = load_known_projects(path)
    if not registry.projects:
        return ProjectConfigScanResult(checked=0, compatible=0, incompatible=())

    compatible = 0
    failures: list[ProjectConfigScanFailure] = []
    for project in registry.projects:
        root = _canonical_root(project.project_root)
        if not root.exists():
            record_known_project(
                path,
                project_root=root,
                checked_at=now,
                config_status="incompatible",
                config_error_code="project-dir-missing",
            )
            failures.append(
                ProjectConfigScanFailure(
                    project_root=root,
                    error_code="project-dir-missing",
                    message=f"known project directory is missing: {root}",
                )
            )
            continue
        try:
            check_project(root)
        except Exception as exc:  # noqa: BLE001
            error_code = getattr(exc, "code", None)
            if not isinstance(error_code, str) or not error_code:
                error_code = "config-incompatible"
            message = str(exc) or "project config failed validation"
            record_known_project(
                path,
                project_root=root,
                checked_at=now,
                config_status="incompatible",
                config_error_code=error_code,
            )
            logger.warning(
                "known gpt-auto project config is incompatible; project blocked",
                extra={"project-root": str(root), "error-code": error_code},
            )
            failures.append(
                ProjectConfigScanFailure(project_root=root, error_code=error_code, message=message)
            )
        else:
            compatible += 1
            record_known_project(
                path,
                project_root=root,
                checked_at=now,
                config_status="compatible",
                config_error_code=None,
            )

    return ProjectConfigScanResult(
        checked=len(registry.projects),
        compatible=compatible,
        incompatible=tuple(failures),
    )


__all__ = [
    "REGISTRY_SCHEMA_VERSION",
    "ConfigStatus",
    "KnownProject",
    "KnownProjectsRegistry",
    "ProjectConfigScanFailure",
    "ProjectConfigScanResult",
    "load_known_projects",
    "record_known_project",
    "scan_known_gpt_auto_projects",
]
