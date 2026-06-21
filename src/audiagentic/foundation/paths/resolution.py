from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error

_RESOLUTION_ORDER = ("project_local", "user_global", "package_default")
_MERGE_ORDER = ("package_default", "user_global", "project_local")


def _path_error(prefix: str, code_number: int, message: str, **details: Any) -> AudiaGenticError:
    return make_error(
        prefix=prefix,
        component="PATH",
        number=code_number,
        kind="paths",
        message=message,
        details=details,
    )


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return new dict with overlay merged on top of base."""
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def build_layered_path_map(
    *,
    package_root: Path | None = None,
    package_default: str | Path | None = None,
    user_global_root: Path | None = None,
    user_global: str | Path | None = None,
    project_root: Path | None = None,
    project_local: str | Path | None = None,
) -> dict[str, Path]:
    """Return absolute per-layer paths from roots plus relative or absolute inputs."""
    path_map: dict[str, Path] = {}
    if package_default is not None:
        path_map["package_default"] = _resolve_path(package_root, package_default)
    if user_global is not None:
        path_map["user_global"] = _resolve_path(user_global_root, user_global)
    if project_local is not None:
        path_map["project_local"] = _resolve_path(project_root, project_local)
    return path_map


def iter_layered_candidates(path_map: dict[str, Path]) -> list[Path]:
    """Return candidate paths in project-local, global, package-default order."""
    return [path_map[layer] for layer in _RESOLUTION_ORDER if layer in path_map]


def resolve_existing_file(path_map: dict[str, Path]) -> Path | None:
    for candidate in iter_layered_candidates(path_map):
        if candidate.is_file():
            return candidate
    return None


def resolve_existing_dir(path_map: dict[str, Path]) -> Path | None:
    for candidate in iter_layered_candidates(path_map):
        if candidate.is_dir():
            return candidate
    return None


def resolve_required_file(path_map: dict[str, Path], *, label: str = "File") -> Path:
    resolved = resolve_existing_file(path_map)
    if resolved is not None:
        return resolved
    raise _path_error(
        "RES",
        1,
        f"{label} not found. Checked: {_format_candidates(path_map)}",
        label=label,
        checked=[str(path) for path in iter_layered_candidates(path_map)],
    )


def resolve_required_dir(path_map: dict[str, Path], *, label: str = "Directory") -> Path:
    resolved = resolve_existing_dir(path_map)
    if resolved is not None:
        return resolved
    raise _path_error(
        "RES",
        2,
        f"{label} not found. Checked: {_format_candidates(path_map)}",
        label=label,
        checked=[str(path) for path in iter_layered_candidates(path_map)],
    )


def load_layered_mapping(
    *,
    package_default_path: Path,
    user_global_path: Path | None = None,
    project_local_path: Path | None = None,
) -> dict[str, Any]:
    """Load mapping from package default, user global, and project local layers."""
    if not package_default_path.exists():
        raise _path_error(
            "CFG",
            3,
            f"Package config missing (reinstall may be needed): {package_default_path}",
            path=str(package_default_path),
        )

    payloads: dict[str, dict[str, Any]] = {
        "package_default": _load_yaml_mapping(package_default_path),
        "user_global": _load_yaml_mapping(user_global_path),
        "project_local": _load_yaml_mapping(project_local_path),
    }
    project_local = dict(payloads["project_local"])
    exclusive_local = bool(project_local.pop("exclusive_local", False))
    payloads["project_local"] = project_local
    if exclusive_local:
        payloads["user_global"] = {}

    result: dict[str, Any] = {}
    for layer in _MERGE_ORDER:
        result = deep_merge(result, payloads[layer])
    return result


def _resolve_path(root: Path | None, value: str | Path) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        return raw.resolve()
    if root is None:
        return raw.resolve()
    return (root / raw).resolve()


def _load_yaml_mapping(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise _path_error("CFG", 4, f"Invalid YAML config: {path}", path=str(path)) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise _path_error("CFG", 5, f"Invalid YAML config: {path} must be a mapping", path=str(path))
    return data


def _format_candidates(path_map: dict[str, Path]) -> str:
    return ", ".join(str(path) for path in iter_layered_candidates(path_map))
