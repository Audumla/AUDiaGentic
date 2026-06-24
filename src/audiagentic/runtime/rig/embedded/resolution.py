from __future__ import annotations

import logging
import os
from pathlib import Path

from audiagentic.foundation.paths.resolution import (
    build_layered_path_map,
    iter_layered_candidates,
    resolve_required_dir,
)
from audiagentic.runtime.rig.constants import (
    platform_binary_names,
    resolve_platform_dirs,
)
from audiagentic.runtime.rig.errors import make_rig_resolution_error

logger = logging.getLogger(__name__)

_GLOBAL_RIG_BIN_REL = Path("rig/bin")
_PROJECT_RIG_BIN_REL = Path("provisioning/rig/embedded/bin")


def _project_audiagentic_root() -> Path | None:
    from audiagentic.paths import find_repo_root

    env_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if env_root:
        return Path(env_root).resolve() / ".audiagentic"
    try:
        return find_repo_root(Path.cwd()) / ".audiagentic"
    except Exception:
        logger.warning("Failed to find repo root", exc_info=True)
        return None


def runtime_bin_dir() -> Path:
    from audiagentic.runtime.home import global_harness_runtime

    path_map = build_layered_path_map(
        user_global_root=global_harness_runtime(),
        user_global=_GLOBAL_RIG_BIN_REL,
        project_root=_project_audiagentic_root(),
        project_local=_PROJECT_RIG_BIN_REL,
    )
    return resolve_required_dir(path_map, label="Rig binary directory")


def resolve_under(root: Path, value: str | None, *, base: Path | None = None) -> Path | None:
    if not value:
        return None
    raw = Path(value)
    resolved = raw if raw.is_absolute() else (base or root) / raw
    return resolved.resolve()


def ensure_under(path: Path, root: Path, label: str) -> Path:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise make_rig_resolution_error(
            "CON",
            1,
            f"{label} must stay under {root}",
            label=label,
            path=str(path),
            root=str(root),
        ) from exc
    return path


def find_server_bin(bin_dir: Path, override: str | None) -> Path:
    server_dir, llamafile_dir = resolve_platform_dirs(bin_dir)
    if override:
        candidate = ensure_under(
            resolve_under(bin_dir, override) or Path(),
            bin_dir,
            "AUDIAGENTIC_RIG_SERVER_BIN",
        )
        if not candidate.exists():
            raise make_rig_resolution_error("RES", 2, f"Rig binary not found: {candidate}", path=str(candidate))
        return candidate

    server_name, fallback_name = platform_binary_names()

    server_bin = server_dir / server_name
    if server_bin.exists():
        return server_bin

    fallback_bin = llamafile_dir / fallback_name
    if fallback_bin.exists():
        return fallback_bin

    raise make_rig_resolution_error("RES", 3, f"Local rig binary not found under {bin_dir}", bin_dir=str(bin_dir))


def resolve_model(bin_dir: Path, server_dir: Path, override: str | None) -> tuple[Path, str]:
    if not override:
        raise make_rig_resolution_error(
            "CFG",
            4,
            "No model file specified. Set --model-file or AUDIAGENTIC_RIG_MODEL_FILE, or add model_file to the profile.",
        )
    candidate = resolve_under(bin_dir, override, base=server_dir)
    assert candidate is not None
    if Path(override).is_absolute():
        if not candidate.exists():
            raise make_rig_resolution_error("RES", 5, f"Model not found: {candidate}", path=str(candidate))
        return candidate, str(candidate)
    ensure_under(candidate, bin_dir, "AUDIAGENTIC_RIG_MODEL_FILE")
    if not candidate.exists():
        layered_candidates = _layered_model_candidates(
            override,
            project_root=_project_audiagentic_root(),
        )
        candidate = _first_existing_model(layered_candidates)
        if candidate is None:
            checked = ", ".join(str(path) for path in layered_candidates)
            raise make_rig_resolution_error(
                "RES",
                6,
                f"Model not found. Checked: {checked}",
                checked=[str(path) for path in layered_candidates],
            )
    if Path(override).is_absolute():
        return candidate, str(candidate)
    try:
        return candidate, candidate.relative_to(server_dir).as_posix()
    except ValueError:
        return candidate, str(candidate)


def _layered_model_candidates(override: str, *, project_root: Path | None) -> list[Path]:
    from audiagentic.runtime.home import global_harness_runtime

    candidates: list[Path] = []
    path_map = build_layered_path_map(
        user_global_root=global_harness_runtime(),
        user_global=_GLOBAL_RIG_BIN_REL,
        project_root=project_root,
        project_local=_PROJECT_RIG_BIN_REL,
    )
    for bin_candidate in iter_layered_candidates(path_map):
        server_dir, _ = resolve_platform_dirs(bin_candidate)
        candidate = resolve_under(bin_candidate, override, base=server_dir)
        assert candidate is not None
        ensure_under(candidate, bin_candidate, "AUDIAGENTIC_RIG_MODEL_FILE")
        candidates.append(candidate)
    return candidates


def _first_existing_model(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
