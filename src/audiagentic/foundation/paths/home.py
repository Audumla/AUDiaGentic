"""Home directory path helpers."""
from __future__ import annotations

from pathlib import Path

import platformdirs

from audiagentic.foundation.paths.names import PROJECT_MARKER_NAME, home_directory

APP_NAME = "audiagentic"


def user_config_dir() -> Path:
    """Platform-standard per-user configuration directory (XDG on Linux).

    The settings model's user scope (docs/design/configuration-model.md).
    Pure path computation: nothing is created.
    """
    return platformdirs.user_config_path(APP_NAME, appauthor=False)


def user_state_dir() -> Path:
    """Platform-standard per-user state directory; nothing is created."""
    return platformdirs.user_state_path(APP_NAME, appauthor=False)


def user_cache_dir() -> Path:
    """Platform-standard per-user cache directory; nothing is created."""
    return platformdirs.user_cache_path(APP_NAME, appauthor=False)


def audiagentic_home() -> Path:
    """Return the shared AUDiaGentic root directory."""
    return home_directory()


def global_harness_runtime() -> Path:
    """Return the harness runtime directory."""
    return audiagentic_home() / "harness"


def global_provider_runtime(provider_id: str) -> Path:
    """Return the managed runtime directory for a provider."""
    return audiagentic_home() / "providers" / provider_id


def global_service_runtime() -> Path:
    """Return the machine-scoped managed-service state directory."""
    return audiagentic_home() / "services"


def global_config_dir() -> Path:
    """Return the machine-scoped shared-service configuration directory."""
    return audiagentic_home() / "config"


def global_log_dir(component: str) -> Path:
    """Return the global log directory for a named component."""
    return audiagentic_home() / "logs" / component


def project_log_dir(project_root: Path, component: str) -> Path:
    """Return the project-scoped log directory for a named component."""
    return project_root / PROJECT_MARKER_NAME / "logs" / component
