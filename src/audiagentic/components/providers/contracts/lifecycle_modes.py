"""Pure helpers that translate user-facing lifecycle verbs and modes to CliLifecycleMode."""
from __future__ import annotations

from audiagentic.components.providers.contracts.cli_lifecycle import CliLifecycleMode

_USER_VERB_TO_MODE = {
    "install": "apply",
    "uninstall": "prune",
    "repair": "apply",
}

_VALID_CLI_MODES: set[str] = {"plan", "apply", "prune", "status"}


def provider_cli_mode_from_user_verb(verb: str) -> CliLifecycleMode:
    """Translate a natural-language user verb to a CLI lifecycle mode.

    Supported verbs: install, uninstall, repair.

    Raises ValueError for unsupported values.
    """
    normalized = verb.strip().lower()
    if normalized not in _USER_VERB_TO_MODE:
        raise ValueError(
            f"Unsupported provider lifecycle verb: {verb!r}. "
            f"Supported verbs: {sorted(_USER_VERB_TO_MODE)}"
        )
    return _USER_VERB_TO_MODE[normalized]  # type: ignore[return-value]


def normalize_provider_cli_mode(mode: str) -> CliLifecycleMode:
    """Normalize and validate an already-semantic CLI lifecycle mode.

    Accepted values: plan, apply, prune, status.

    Raises ValueError for unsupported values.
    """
    normalized = mode.strip().lower()
    if normalized not in _VALID_CLI_MODES:
        raise ValueError(
            f"Unsupported provider CLI lifecycle mode: {mode!r}. "
            f"Supported modes: {sorted(_VALID_CLI_MODES)}"
        )
    return normalized  # type: ignore[return-value]


__all__ = [
    "normalize_provider_cli_mode",
    "provider_cli_mode_from_user_verb",
]
