"""Gateway settings: the ``gateway`` section of the resolved settings (CFG09).

The section's schema is ``config/components/agents/settings/gateway.schema.json``.
The gateway is shared by every project and session on the machine, so this
section is read from the machine scopes only (vendor, user, explicit file); a
project's own settings never change it. Values come from
``resolve_settings_cached``, so an edited file applies on the next read. There is
no environment or legacy-file fallback.

A settings file that stops validating must not take a running gateway down.
Reads made once, to decide something (the port, the implementation, the queue
backend), are strict and raise with the file, line and key. Reads made repeatedly
by a running service (the console trace, the idle-grace loop, the dashboard window)
pass ``strict=False``: they keep the last value that validated, log the problem
once, and carry on. Destructive policies (``gateway_policy``) fail closed instead.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_last_valid: dict[str, Any] = {}
_last_reported = ""


def gateway_setting(key: str, default: Any = None, *, strict: bool = True) -> Any:
    """``gateway.<key>`` (dotted for nested keys), else ``default``.

    With ``strict=False`` an invalid settings file yields the last valid value (or
    ``default`` if none was ever read) and is logged once; otherwise it raises.
    """
    value: Any = _gateway_section() if strict else _gateway_section_or_last_valid()
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

    global _last_valid, _last_reported
    section = resolve_settings_cached(machine_only=True).get("gateway")
    _last_valid = section if isinstance(section, dict) else {}
    _last_reported = ""
    return _last_valid


def _gateway_section_or_last_valid() -> dict[str, Any]:
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    global _last_reported
    try:
        return _gateway_section()
    except AudiaGenticError as exc:
        message = str(exc)
        if message != _last_reported:  # once per distinct problem, not once per trace line
            _last_reported = message
            logger.warning("gateway settings are invalid; keeping the last valid values: %s", message)
        return _last_valid


__all__ = ["gateway_policy", "gateway_setting"]
