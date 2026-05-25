"""Lifecycle component events published to the foundation event bus.

Event types follow the dot-notation convention: lifecycle.component.{verb}

Subscribers (e.g. the providers surface observer) subscribe to "lifecycle.component.*"
or specific events on the shared bus. No direct dependency between the lifecycle layer
and its observers — fully decoupled through the bus.

Payload schema:
  component_id : str   — the component that changed state
  project_root : Path  — project root Path (in-process, not serialized)
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.event import DeliveryMode, get_bus

COMPONENT_INSTALLED = "lifecycle.component.installed"
COMPONENT_UNINSTALLED = "lifecycle.component.uninstalled"
COMPONENT_ENABLED = "lifecycle.component.enabled"
COMPONENT_DISABLED = "lifecycle.component.disabled"


def _publish(event: str, component_id: str, project_root: Path) -> None:
    get_bus().publish(
        event,
        {"component_id": component_id, "project_root": project_root},
        metadata={"source_component": "lifecycle", "subject": {"kind": "component", "id": component_id}},
        mode=DeliveryMode.SYNC,
    )


def fire_post_install(component_id: str, project_root: Path) -> None:
    _publish(COMPONENT_INSTALLED, component_id, project_root)


def fire_post_uninstall(component_id: str, project_root: Path) -> None:
    _publish(COMPONENT_UNINSTALLED, component_id, project_root)


def fire_post_enable(component_id: str, project_root: Path) -> None:
    _publish(COMPONENT_ENABLED, component_id, project_root)


def fire_post_disable(component_id: str, project_root: Path) -> None:
    _publish(COMPONENT_DISABLED, component_id, project_root)
