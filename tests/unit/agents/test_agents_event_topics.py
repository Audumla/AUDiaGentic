from __future__ import annotations

from audiagentic.components.agents import agents_event_topics as topics
from audiagentic.foundation.event.topic_registry import (
    get_topic_registry,
    load_all_event_topics,
)


def test_as26_orphaned_session_topic_is_registered() -> None:
    load_all_event_topics()
    registry = get_topic_registry()

    assert topics.SESSION_ORPHANED_TOPIC == "agents.session.orphaned"
    assert registry.is_registered(topics.SESSION_ORPHANED_TOPIC)
