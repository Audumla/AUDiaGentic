from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.ledger import ledger_api
from audiagentic.components.release.events import RELEASE_LEDGER_ARCHIVE_REQUESTED
from audiagentic.foundation.event import get_bus

_REGISTERED_BUS_ID: int | None = None


def _on_release_ledger_archive_requested(
    event_type: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    project_root = payload.get("project_root")
    release_id = payload.get("release_id")
    result_slot = payload.get("result")
    if not isinstance(project_root, Path) or not isinstance(release_id, str) or not isinstance(result_slot, dict):
        return
    result_slot.update(ledger_api.archive_for_release(project_root, release_id))


def register() -> None:
    global _REGISTERED_BUS_ID
    bus = get_bus()
    bus_id = id(bus)
    if _REGISTERED_BUS_ID == bus_id:
        return
    bus.subscribe(RELEASE_LEDGER_ARCHIVE_REQUESTED, _on_release_ledger_archive_requested)
    _REGISTERED_BUS_ID = bus_id


register()
