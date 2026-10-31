"""Observations: facts the system learned, kept as state and never as configuration.

Availability probes, qualification results and reconcile outcomes live in
``<project>/.audiagentic/state/observations/<component>.yaml`` (ignored by git). Each entry keeps
the value, when it was observed and who recorded it, so a reader can apply its own staleness rule.
Writers hold an advisory lock and replace the file atomically. Nothing here reads or writes settings.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import load_yaml_file, save_yaml_file
from audiagentic.foundation.paths.names import PROJECT_MARKER_NAME
from audiagentic.foundation.system.advisory_lock import AdvisoryLock

OBSERVATIONS_DIR = Path(PROJECT_MARKER_NAME) / "state" / "observations"


def observations_path(project_root: Path, component: str) -> Path:
    if not component or "/" in component or component.startswith("."):
        raise ValueError(f"invalid component id: {component!r}")
    return project_root / OBSERVATIONS_DIR / f"{component}.yaml"


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = load_yaml_file(path)
    return data if isinstance(data, dict) else {}


def record_observation(
    project_root: Path, component: str, key: str, value: Any, *, source: str, now: datetime | None = None,
) -> None:
    path = observations_path(project_root, component)
    stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with AdvisoryLock(path.with_suffix(".lock")):
        data = _load(path)
        data[key] = {"value": value, "observed-at": stamp, "source": source}
        save_yaml_file(path, data, sort_keys=True, atomic=True)


def get_observation(
    project_root: Path, component: str, key: str, *, max_age: timedelta | None = None,
    now: datetime | None = None,
) -> Any | None:
    """The recorded value, or ``None`` when absent or older than ``max_age``."""
    entry = _load(observations_path(project_root, component)).get(key)
    if not isinstance(entry, dict) or "value" not in entry:
        return None
    if max_age is not None:
        try:
            seen = datetime.fromisoformat(str(entry.get("observed-at")))
        except ValueError:
            return None
        if (now or datetime.now(UTC)) - seen > max_age:
            return None
    return entry["value"]


def observed_keys(project_root: Path, component: str, prefix: str = "") -> list[str]:
    """Recorded keys of one component, optionally only those starting with ``prefix``."""
    return sorted(key for key in _load(observations_path(project_root, component)) if key.startswith(prefix))


def clear_observation(project_root: Path, component: str, key: str) -> bool:
    path = observations_path(project_root, component)
    if not path.is_file():
        return False
    with AdvisoryLock(path.with_suffix(".lock")):
        data = _load(path)
        if key not in data:
            return False
        del data[key]
        save_yaml_file(path, data, sort_keys=True, atomic=True)
    return True


__all__ = ["OBSERVATIONS_DIR", "clear_observation", "get_observation", "observations_path", "observed_keys", "record_observation"]
