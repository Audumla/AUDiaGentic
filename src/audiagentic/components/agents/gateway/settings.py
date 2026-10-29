"""Gateway settings: the ``gateway`` section of the resolved settings (CFG09).

The section's schema is ``config/components/agents/settings/gateway.schema.json``.
The gateway is shared by every project and session on the machine, so this
section is read from the machine scopes only (vendor, user, explicit file); a
project's own settings never change it. Values come from
``resolve_settings_cached``, so an edited file applies on the next read. There is
no environment or legacy-file fallback.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def gateway_setting(key: str, default: Any = None) -> Any:
    """``gateway.<key>`` (dotted for nested keys), else ``default``."""
    value: Any = _gateway_section()
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def gateway_policy(section: str) -> dict[str, Any] | None:
    """``gateway.<section>`` as the kebab-case mapping the policy loaders read, or None if unset.

    Invalid settings raise ``ValueError`` so callers treat the policy as invalid
    (purges and deletions off) and an operator sees why in the log.
    """
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    try:
        configured = _gateway_section().get(section)
    except AudiaGenticError as exc:
        logger.warning("gateway.%s policy is invalid: settings did not validate: %s", section, exc)
        raise ValueError(str(exc)) from exc
    if configured is None:
        return None
    return {key.replace("_", "-"): value for key, value in configured.items()}


def _gateway_section() -> dict[str, Any]:
    from audiagentic.foundation.config.settings import resolve_settings_cached

    section = resolve_settings_cached(machine_only=True).get("gateway")
    return section if isinstance(section, dict) else {}


__all__ = ["gateway_policy", "gateway_setting"]
