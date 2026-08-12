"""Load event topic registrations from component config files.

Scans each component's config directory for ``events.yaml`` and registers
topic specifications with the topic registry. Validates against
``event-topics.schema.json`` and rejects duplicate topics across owners.

File format (YAML):
    agents.execution.completed:
      description: "Gateway request completed"
      payload-required: ["request-id", "state"]
      payload-optional: ["provider-id", "model-id"]
      metadata-keys: []
      delivery: async
      since: v1.0.0

Registry files are optional — components without them simply have no registered topics.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.paths.names import get_component_config_dirs

logger = logging.getLogger(__name__)

# Topic naming grammar: dotted lowercase, at least 2 segments (e.g. interaction.requested)
# The standard (§17) specifies <domain>.<resource>.<action> with 3 segments,
# but pre-existing 2-segment topics are allowed until BU02 migration.
_TOPIC_RE = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]+)+$")


@dataclass(frozen=True)
class EventTopicSpec:
    """Canonical spec for a registered event topic."""

    owner: str
    description: str
    payload_required: list[str] = field(default_factory=list)
    payload_optional: list[str] = field(default_factory=list)
    metadata_keys: list[str] = field(default_factory=list)
    delivery: str = "async"
    since: str = ""


class TopicRegistry:
    """Global event topic registry — the single source of truth for published topics."""

    def __init__(self) -> None:
        self._topics: dict[str, EventTopicSpec] = {}
        self._owners: dict[str, set[str]] = {}  # component_id -> {topic, ...}

    @property
    def topics(self) -> dict[str, EventTopicSpec]:
        return dict(self._topics)

    @property
    def owners(self) -> dict[str, set[str]]:
        return {k: set(v) for k, v in self._owners.items()}

    def register_topic(
        self,
        topic: str,
        spec: EventTopicSpec,
    ) -> None:
        """Register or replace a topic specification.

        Raises AudiaGenticError if the same topic is declared by two different owners.
        Same-owner overlay follows last-wins precedence.
        """
        if not _TOPIC_RE.match(topic):
            raise AudiaGenticError(
                code="CON-EVT-010",
                kind="event-registry",
                message=f"topic name violates naming grammar: {topic!r}",
                details={
                    "topic": topic,
                    "grammar": "dotted lowercase <domain>.<resource>.<action> with past-tense actions",
                },
            )

        existing = self._topics.get(topic)
        if existing and existing.owner != spec.owner:
            raise AudiaGenticError(
                code="CON-EVT-011",
                kind="event-registry",
                message=f"topic {topic!r} is claimed by two owners: {existing.owner!r} and {spec.owner!r}",
                details={"topic": topic, "existing_owner": existing.owner, "new_owner": spec.owner},
            )

        self._topics[topic] = spec
        self._owners.setdefault(spec.owner, set()).add(topic)

    def get_topic(self, topic: str) -> EventTopicSpec | None:
        return self._topics.get(topic)

    def is_registered(self, topic: str) -> bool:
        return topic in self._topics


def _validate_schema(data: dict[str, Any], path: Path) -> None:
    """Validate events.yaml content against event-topics.schema.json."""
    try:
        import json

        from jsonschema import validate  # noqa: PLC0415
    except ImportError:
        logger.warning(
            "jsonschema not installed; skipping events.yaml schema validation for %s", path
        )
        return

    schema_path = (
        Path(__file__).parent.parent / "contracts" / "schemas" / "event-topics.schema.json"
    )
    try:
        with open(schema_path) as f:
            schema = json.load(f)
    except OSError:
        logger.warning("events.yaml schema file missing; skipping validation for %s", path)
        return
    try:
        validate(instance=data, schema=schema)
    except Exception as exc:  # noqa: BLE001 — ValidationError from jsonschema
        raise AudiaGenticError(
            code="VAL-EVT-012",
            kind="event-registry",
            message=f"events.yaml validation error in {path}: {exc}",
            details={"path": str(path)},
        ) from exc


# Singleton registry instance
_registry_instance: TopicRegistry | None = None
_fully_loaded: bool = False


def get_topic_registry() -> TopicRegistry:
    """Return the singleton TopicRegistry (lazy-loaded)."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = TopicRegistry()
    return _registry_instance


def load_event_topics_from_component(component_id: str, config_dir: Path) -> int:
    """Load event topic registrations from a component's ``events.yaml``.

    Returns the number of topics registered.
    """
    events_path = config_dir / component_id / "events.yaml"
    if not events_path.exists():
        return 0

    data = load_yaml_file(events_path)
    _validate_schema(data, events_path)

    count = 0
    for topic, spec_data in data.items():
        if not isinstance(topic, str):
            logger.warning("Skipping non-string topic key in %s: %r", events_path, topic)
            continue
        if not isinstance(spec_data, dict):
            logger.warning(
                "Skipping invalid spec in %s for topic %r: expected mapping", events_path, topic
            )
            continue
        try:
            spec = EventTopicSpec(
                owner=component_id,
                description=str(spec_data.get("description", "")),
                payload_required=list(spec_data.get("payload-required", [])),
                payload_optional=list(spec_data.get("payload-optional", [])),
                metadata_keys=list(spec_data.get("metadata-keys", [])),
                delivery=str(spec_data.get("delivery", "async")),
                since=str(spec_data.get("since", "")),
            )
            get_topic_registry().register_topic(topic, spec)
            count += 1
        except AudiaGenticError:
            raise
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to register topic %r from %s",
                topic,
                events_path,
                exc_info=True,
            )
    return count


def load_all_event_topics(config_dirs: list[Path] | None = None) -> int:
    """Load event topics from all registered component config directories.

    Uses the shared resolver in foundation/paths/names.py — the same override
    source as loader.register_all_components and error-resolution loading.

    Returns total number of topics loaded across all components.
    """
    targets = config_dirs or get_component_config_dirs()
    total = 0
    for config_dir in targets:
        if not config_dir.exists():
            continue
        for component_dir in sorted(config_dir.glob("*")):
            if not component_dir.is_dir():
                continue
            component_id = component_dir.name
            try:
                total += load_event_topics_from_component(component_id, config_dir)
            except AudiaGenticError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to load event topics for %s",
                    component_id,
                    exc_info=True,
                )
    global _fully_loaded
    _fully_loaded = True
    return total


def assert_event_payload(
    topic: str,
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Assert that a publish payload conforms to the registered topic spec.

    Test-time hook only — never called in the publish path. Validates required
    payload keys and metadata keys against the EventTopicSpec for *topic*.

    Raises AssertionError naming the topic when unregistered, naming missing
    keys against spec.payload_required, and naming missing metadata keys
    against spec.metadata_keys when metadata is provided.
    """
    global _registry_instance, _fully_loaded

    if not _fully_loaded:
        # Save scratch registrations from a partially-loaded test singleton,
        # then do a clean full load.
        saved_topics: dict[str, EventTopicSpec] = {}
        if _registry_instance is not None:
            saved_topics = _registry_instance.topics
        _registry_instance = None
        _fully_loaded = False
        load_all_event_topics()
        # Restore scratch registrations that weren't in the full load
        new_registry: TopicRegistry | None = _registry_instance
        for t, spec in saved_topics.items():
            if new_registry and not new_registry.is_registered(t):
                try:
                    new_registry.register_topic(t, spec)
                except AudiaGenticError:
                    pass
    registry = get_topic_registry()
    spec = registry.get_topic(topic)
    assert spec is not None, f"topic {topic!r} is not registered in any events.yaml"
    missing = [k for k in spec.payload_required if k not in payload]
    if missing:
        raise AssertionError(f"topic {topic!r} missing required payload keys: {missing}")
    if metadata is not None and spec.metadata_keys:
        missing_meta = [k for k in spec.metadata_keys if k not in metadata]
        if missing_meta:
            raise AssertionError(f"topic {topic!r} missing required metadata keys: {missing_meta}")
