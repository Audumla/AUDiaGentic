"""CC54: catalog.py and surfaces/manager.py's _emit must fall back to
push_status when no on_progress callback is wired, same as lifecycle.py's
_emit already did. Previously they silently dropped the message instead.
"""
from __future__ import annotations

from audiagentic.foundation import interaction


class _Backend:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []

    def ask(self, request):  # pragma: no cover - unused here
        raise NotImplementedError

    def push_status(self, msg) -> None:
        self.messages.append((msg.component, msg.level, msg.message))

    def respond(self, request_id, choice, *, details):  # pragma: no cover - unused here
        pass


def teardown_function() -> None:
    interaction.clear_backend()


def test_catalog_emit_falls_back_to_push_status() -> None:
    from audiagentic.components.providers.services.catalog.catalog import _emit

    backend = _Backend()
    interaction.set_backend(backend)

    _emit(None, "catalog refresh started", level="warning")

    assert backend.messages == [("providers", "warning", "catalog refresh started")]


def test_surfaces_manager_emit_falls_back_to_push_status() -> None:
    from audiagentic.components.providers.surfaces.manager import _emit

    backend = _Backend()
    interaction.set_backend(backend)

    _emit(None, "surface applied", level="info", provider_id="claude")

    assert backend.messages == [("providers", "info", "surface applied")]


def test_lifecycle_emit_still_falls_back_to_push_status() -> None:
    """Regression: lifecycle.py's _emit already did this correctly before CC54."""
    from audiagentic.components.providers.services.lifecycle.lifecycle import _emit

    backend = _Backend()
    interaction.set_backend(backend)

    _emit(None, "reconciling codex")

    assert backend.messages == [("providers", "info", "reconciling codex")]


def test_output_sink_still_takes_priority_over_push_status() -> None:
    from audiagentic.components.providers.services.catalog.catalog import _emit
    from audiagentic.foundation.contracts.output import ComponentOutputEvent

    backend = _Backend()
    interaction.set_backend(backend)

    events: list[ComponentOutputEvent] = []
    _emit(events.append, "catalog refresh started", level="warning")

    assert backend.messages == []
    assert len(events) == 1
    assert events[0].message == "catalog refresh started"
    assert events[0].level == "warning"
    assert events[0].kind == "log"
