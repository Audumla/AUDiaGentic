"""Single source of truth for .audiagentic / audiagentic directory names.

All code that references the project marker directory (.audiagentic) or the
package root directory (audiagentic) must import these constants or functions,
never hardcode the literals. This is the central resolver for profile-aware
path construction.
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Named constants ────────────────────────────────────────────────────────

PROJECT_MARKER_NAME = ".audiagentic"
"""Marker directory that identifies a project root."""

PACKAGE_ROOT_NAME = "audiagentic"
"""Package root directory name inside the source tree."""

CONFIG_DIR_NAME = "config"
"""Config subdirectory inside .audiagentic/ — source-of-truth config."""

RUNTIME_DIR_NAME = "runtime"
"""Runtime subdirectory inside .audiagentic/ — cache, logs, temp data."""

LINTING_DIR_NAME = "linting"
"""Linting subdirectory inside .audiagentic/config/ — shared lint rules."""

CACHE_DIR_NAME = "cache"
"""Cache subdirectory inside .audiagentic/runtime/ — safely deletable."""

LOGS_DIR_NAME = "logs"
"""Logs subdirectory inside .audiagentic/runtime/ — component logs."""


# ── Package root resolution ───────────────────────────────────────────────


def find_package_root(start: Path | None = None) -> Path:
    """Walk up from *start* (default this file's parent) until a directory
    named ``PACKAGE_ROOT_NAME`` is found. Replaces the scattered
    ``Path(__file__).resolve().parents[N]`` pattern across the codebase.
    """
    from audiagentic.foundation.contracts.errors import make_error

    current = (start or Path(__file__)).resolve()
    while current != current.parent:
        if current.name == PACKAGE_ROOT_NAME:
            return current
        current = current.parent
    raise make_error(
        prefix="RES",
        component="PATH",
        number=6,
        kind="paths",
        message=f"Could not find '{PACKAGE_ROOT_NAME}' package root from {start}",
        details={"start": str(start)},
    )


def get_package_config_dir() -> Path:
    """Return the config directory shipped with the package
    (e.g. src/audiagentic/config/)."""
    return find_package_root() / "config"


def get_package_components_config_dir() -> Path:
    """Return the component descriptor config directory
    (e.g. src/audiagentic/config/components/)."""
    return get_package_config_dir() / "components"


def get_package_providers_config_dir() -> Path:
    """Return the provider definitions config directory
    (e.g. src/audiagentic/config/providers/)."""
    return get_package_config_dir() / "providers"


# ── Project marker resolution ─────────────────────────────────────────────


def project_marker_path(project_root: Path) -> Path:
    """Return the .audiagentic marker directory inside a project root."""
    return project_root / PROJECT_MARKER_NAME


def project_config_dir(project_root: Path) -> Path:
    """Return .audiagentic/config/ — source-of-truth config location."""
    return project_marker_path(project_root) / CONFIG_DIR_NAME


def project_runtime_dir(project_root: Path) -> Path:
    """Return .audiagentic/runtime/ — cache, logs, temp data."""
    return project_marker_path(project_root) / RUNTIME_DIR_NAME


def project_cache_dir(project_root: Path) -> Path:
    """Return .audiagentic/runtime/cache/ — safely deletable cache data."""
    return project_runtime_dir(project_root) / CACHE_DIR_NAME


def project_linting_dir(project_root: Path) -> Path:
    """Return .audiagentic/config/linting/ — shared lint rules."""
    return project_config_dir(project_root) / LINTING_DIR_NAME


def project_logs_dir(project_root: Path) -> Path:
    """Return .audiagentic/runtime/logs/ — component logs."""
    return project_runtime_dir(project_root) / LOGS_DIR_NAME


def home_directory() -> Path:
    """Return the user's ~/.audiagentic/ home directory.
    Replaces inline Path.home() / '.audiagentic' patterns."""
    custom = os.environ.get("AUDIAGENTIC_HOME")
    if custom:
        return Path(custom)
    return Path.home() / PROJECT_MARKER_NAME


# ── Component config directory resolution ─────────────────────────────────


def get_component_config_dirs() -> list[Path]:
    """Resolve base component config directories from override sources.

    Checks the AUDIAGENTIC_COMPONENT_CONFIG_DIRS env var (comma-separated
    paths) first, then falls back to the shipped package default. Single
    source of truth shared by the component loader and error-resolution
    loading so the two can never drift into different precedence.
    """
    override = os.environ.get("AUDIAGENTIC_COMPONENT_CONFIG_DIRS")
    if override:
        return [Path(p.strip()) for p in override.split(",")]
    return [get_package_components_config_dir()]


# ── Profile-aware paths (CP03/CP04) ────────────────────────────────────────


def resolve_profile_root(
    project_root: Path,
    profile_name: str | None = None,
) -> Path:
    """Compute the profile-aware config root directory.

    When *profile_name* is ``None`` or equal to ``PACKAGE_ROOT_NAME``,
    returns the base marker directory (current behavior).  When a named
    profile is given, returns the subdirectory::

        project_root/.audiagentic/<profile_name>/

    Pure resolution — never creates the directory.
    """
    if not profile_name or profile_name == PACKAGE_ROOT_NAME:
        return project_marker_path(project_root)
    return project_marker_path(project_root) / profile_name


def resolve_profile_component_config_dir(
    project_root: Path,
    profile_name: str,
) -> Path:
    """Return the component descriptor directory for a named profile:
    ``project_root/.audiagentic/<profile_name>/components/``."""
    return resolve_profile_root(project_root, profile_name) / "components"


def get_active_profile() -> str | None:
    """Return the currently active component profile name (from env var).

    Returns None when using base (default) behavior.
    The env var is set by the CLI --component-profile flag or manually.
    """
    name = os.environ.get("AUDIAGENTIC_COMPONENT_PROFILE")
    if not name or name == PACKAGE_ROOT_NAME:
        return None
    return name
