"""The project checkouts a machine's gateway clients may search: ``gateway.workspace_roots``."""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError


def configured_workspace_roots() -> list[Path]:
    """The resolved ``gateway.workspace_roots`` from the machine settings; empty when unset or unreadable."""
    from audiagentic.foundation.config.settings import resolve_settings_cached

    try:
        value = resolve_settings_cached(machine_only=True).get("gateway.workspace_roots")
    except AudiaGenticError:
        return []
    return [Path(item).expanduser().resolve() for item in value or [] if str(item).strip()]
