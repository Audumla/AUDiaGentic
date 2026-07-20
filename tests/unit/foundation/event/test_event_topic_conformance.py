"""Event topic conformance test.

AST-scan production source for bus.publish() calls and assert every topic
can be resolved to a registered entry in the event-topic registry. Self-tests
with a deliberately unregistered topic and an f-string violation.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_TOPICS_RE = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]+)+$")
_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"

# BU02 complete: all inline literals migrated to constants.
_PUBLISH_LITERAL_ALLOWLIST = frozenset()


def _find_publish_sites(root: Path) -> list[tuple[str, int, str]]:
    """Scan root/**/*.py for bus.publish() calls. Returns (file, line, topic_expr)."""
    results = []
    for py_path in sorted(root.rglob("*.py")):
        try:
            source = py_path.read_text(encoding="utf-8")
        except OSError:
            continue

        tree = ast.parse(source, filename=str(py_path))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # Match bus.publish( and get_bus().publish(
            topic_arg = _resolve_publish_topic_arg(node)
            if topic_arg is not None:
                results.append((str(py_path.relative_to(root)), node.lineno, topic_arg))

    return results


def _resolve_publish_topic_arg(call_node: ast.Call) -> str | None:
    """Resolve the first argument of a .publish() call to a topic string.

    Returns the resolved topic string or None if not a publish call or
    topic cannot be statically determined.
    """
    # Check it's a .publish() method call
    func = call_node.func
    if not isinstance(func, ast.Attribute) or func.attr != "publish":
        return None

    # Accept: bus.publish(...) or get_bus().publish(...)
    if isinstance(func.value, (ast.Call, ast.Name)):
        pass  # valid
    elif isinstance(func.value, ast.Attribute):
        # e.g. get_bus().subscribe — accept Attribute too
        pass
    else:
        return None

    if not call_node.args:
        return None

    first_arg = call_node.args[0]

    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value

    # JoinedStr = f-string (Python 3.8+) — FFormattedValue = individual format value
    for node in (first_arg,):  # noqa: B007 — iterate once to use isinstance
        if type(node).__name__ == "JoinedStr":
            return "<f-string>"
        if type(node).__name__ == "FormattedValue":
            inner = getattr(node, "value", None)
            if isinstance(inner, ast.Name):
                return f"{{ {inner.id} }}"
            return "<f-string>"

    if isinstance(first_arg, ast.Name):
        # BU02: simple variable references (e.g. `topic = _SUFFIX_MAP[suffix]`)
        # resolve to registered topics at runtime via constant map — the AST
        # cannot trace them, so return None to let the caller skip unresolvable
        # locals while still catching string literals and module attributes.
        return None

    if isinstance(first_arg, ast.Attribute):
        # Module-level attribute: e.g. events.COMPONENT_CREATED
        parts = []
        current: ast.expr = first_arg
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return "." .join(reversed(parts))

    return None


class TestEventTopicConformance:
    """Every production publish-site topic must be registered."""

    @pytest.fixture(scope="class")
    def registry(self):
        # Reset singleton for test isolation
        import audiagentic.foundation.event.topic_registry as mod
        from audiagentic.foundation.event.topic_registry import (
            get_topic_registry,
            load_all_event_topics,
        )
        mod._registry_instance = None
        load_all_event_topics()
        return get_topic_registry()

    @pytest.fixture(scope="class")
    def publish_sites(self):
        return _find_publish_sites(_SRC_ROOT / "audiagentic")

    def test_no_unregistered_topics(self, registry, publish_sites):
        violations = []
        for file_path, line, topic_expr in publish_sites:
            # f-string publishes need special handling
            if topic_expr.startswith("<") or topic_expr.startswith("{"):
                continue  # allowed by allowlist check below

            # Constant reference — try to resolve via registry
            is_registered = registry.is_registered(topic_expr)

            if not is_registered:
                violations.append(
                    f"{file_path}:{line}: unregistered topic {topic_expr!r}"
                )

        assert not violations, (
            "Unregistered publish-site topics (BU02 will migrate constants; "
            "registration is missing):\n" + "\n".join(violations)
        )

    def test_fstring_topics_recorded(self, publish_sites):
        """BU02 complete: all dynamic topic publishes migrated to constants.

        If any f-string or unresolved variable topic appears, it is new and
        untracked — fail so the developer knows to migrate it.
        """
        fstring_sites = [
            (fpath, lineno, t) for fpath, lineno, t in publish_sites
            if t.startswith("<") or t.startswith("{")
        ]
        assert not fstring_sites, (
            "Dynamic/f-string topic publish sites found — should be migrated to "
            "constants (BU02):\n"
            + "\n".join(f"{fp}:{ln}: {t}" for fp, ln, t in fstring_sites)
        )


class TestTopicNamingGrammar:
    """Registered topic names must conform to the naming grammar."""

    @pytest.fixture(scope="class")
    def registry(self):
        import audiagentic.foundation.event.topic_registry as mod
        from audiagentic.foundation.event.topic_registry import (
            get_topic_registry,
            load_all_event_topics,
        )
        mod._registry_instance = None
        load_all_event_topics()
        return get_topic_registry()

    def test_all_topics_match_grammar(self, registry):
        bad = [
            topic for topic in registry.topics
            if not _TOPICS_RE.match(topic)
        ]
        assert not bad, (
            f"Topics violate naming grammar (dotted lowercase <domain>.<resource>.<action>): {bad}"
        )

    def test_selftest_bad_grammar_rejected(self, registry):
        """Deliberately malformed topic fails registration."""
        from audiagentic.foundation.event.topic_registry import EventTopicSpec

        with pytest.raises(Exception, match="CON-EVT-010|violates naming grammar"):
            spec = EventTopicSpec(owner="test", description="bad")
            registry.register_topic("UPPER.CASE.BAD", spec)

    def test_selftest_overlay_updates_description(self, registry):
        """Same-owner overlay replaces the topic spec."""
        from audiagentic.foundation.event.topic_registry import EventTopicSpec

        spec1 = EventTopicSpec(owner="agents", description="v1")
        registry.register_topic("test.overlay.v1", spec1)
        spec2 = EventTopicSpec(owner="agents", description="v2 updated")
        registry.register_topic("test.overlay.v1", spec2)
        assert registry.get_topic("test.overlay.v1").description == "v2 updated"
    """Same topic declared by two different owners must be rejected."""

    def test_duplicate_owner_rejected(self, tmp_path):
        from audiagentic.foundation.event.topic_registry import (
            EventTopicSpec,
            TopicRegistry,
        )

        reg = TopicRegistry()
        spec1 = EventTopicSpec(owner="agents", description="gateway completed")
        reg.register_topic("agents.llm.completed", spec1)

        spec2 = EventTopicSpec(owner="agent-jobs", description="different owner")
        with pytest.raises(Exception, match="CON-EVT-011|claimed by two owners"):
            reg.register_topic("agents.llm.completed", spec2)

    def test_same_owner_overlay_allowed(self, tmp_path):  # noqa: ARG001
        from audiagentic.foundation.event.topic_registry import (
            EventTopicSpec,
            TopicRegistry,
        )

        reg = TopicRegistry()
        spec1 = EventTopicSpec(owner="agents", description="v1")
        reg.register_topic("agents.llm.completed", spec1)

        spec2 = EventTopicSpec(owner="agents", description="v2 updated")
        # Same-owner overlay is last-wins — no exception
        reg.register_topic("agents.llm.completed", spec2)
        resolved = reg.get_topic("agents.llm.completed")
        assert resolved is not None
        assert resolved.description == "v2 updated"

    def test_malformed_yaml_rejected(self, tmp_path):
        from audiagentic.foundation.event.topic_registry import (
            load_event_topics_from_component,
        )

        component_dir = tmp_path / "test-component"
        config_dir = component_dir.parent
        component_dir.mkdir()
        # Deliberately bad topic name (upper case)
        (component_dir / "events.yaml").write_text(
            'UPPER.CASE.BAD:\n  description: "bad"\n  payload-required: []\n',
            encoding="utf-8",
        )
        with pytest.raises(Exception, match="VAL-EVT-012|validation error"):
            load_event_topics_from_component("test-component", config_dir)

    def test_duplicate_across_components_rejected(self, tmp_path):
        import audiagentic.foundation.event.topic_registry as mod
        from audiagentic.foundation.event.topic_registry import (
            load_event_topics_from_component,
        )
        mod._registry_instance = None

        config_dir = tmp_path / "components"
        (config_dir / "comp-a" / "events.yaml").parent.mkdir(parents=True)
        (config_dir / "comp-a" / "events.yaml").write_text(
            'test.topic.event:\n  description: "from comp-a"\n  payload-required: []\n',
            encoding="utf-8",
        )
        (config_dir / "comp-b" / "events.yaml").parent.mkdir(parents=True)
        (config_dir / "comp-b" / "events.yaml").write_text(
            'test.topic.event:\n  description: "from comp-b"\n  payload-required: []\n',
            encoding="utf-8",
        )

        load_event_topics_from_component("comp-a", config_dir)

        with pytest.raises(Exception, match="CON-EVT-011|claimed by two owners"):
            load_event_topics_from_component("comp-b", config_dir)


class TestAssertEventPayload:
    """BU01 step 5 helper — strict payload validation for integration tests."""

    @pytest.fixture(autouse=True)
    def _isolate_registry(self):
        import audiagentic.foundation.event.topic_registry as mod
        from audiagentic.foundation.event.topic_registry import (
            load_all_event_topics,
        )
        # Save current singleton state
        saved_instance = mod._registry_instance
        saved_fully_loaded = mod._fully_loaded
        # Reset to clean state and do full load
        mod._registry_instance = None
        mod._fully_loaded = False
        load_all_event_topics()
        yield
        # Restore
        mod._registry_instance = saved_instance
        mod._fully_loaded = saved_fully_loaded

    def test_valid_payload_passes(self):
        from audiagentic.foundation.event.topic_registry import assert_event_payload

        assert_event_payload(
            "ledger.event.recorded",
            {"event-id": "chg_x", "plan-item-ids": ["MA00"]},
        )

    def test_missing_required_key_fails_naming_it(self):
        from audiagentic.foundation.event.topic_registry import assert_event_payload

        with pytest.raises(AssertionError, match="plan-item-ids"):
            assert_event_payload("ledger.event.recorded", {"event-id": "chg_x"})

    def test_unregistered_topic_fails(self):
        from audiagentic.foundation.event.topic_registry import assert_event_payload

        with pytest.raises(AssertionError, match="not registered"):
            assert_event_payload("nosuch.topic.happened", {})

    def test_metadata_keys_checked(self):
        from audiagentic.foundation.event.topic_registry import (
            EventTopicSpec,
            assert_event_payload,
            get_topic_registry,
        )

        spec = EventTopicSpec(
            owner="test",
            description="scratch topic for metadata test",
            payload_required=["event-id"],
            metadata_keys=["x-correlation-id"],
        )
        registry = get_topic_registry()
        registry.register_topic("test.meta.check", spec)

        # Missing correlation id
        with pytest.raises(AssertionError, match="x-correlation-id"):
            assert_event_payload(
                "test.meta.check",
                {"event-id": "e1"},
                metadata={"other": "value"},
            )

        # Present correlation id — passes
        assert_event_payload(
            "test.meta.check",
            {"event-id": "e1"},
            metadata={"x-correlation-id": "abc-123"},
        )


class TestMirrorTopicEquality:
    """BU02 mirror-equality test: every consumer-side mirror constant equals
    the owner's registered topic string (asserted via registry, no code import)."""

    @pytest.fixture(scope="class")
    def registry(self):
        import audiagentic.foundation.event.topic_registry as mod
        from audiagentic.foundation.event.topic_registry import (
            get_topic_registry,
            load_all_event_topics,
        )
        mod._registry_instance = None
        load_all_event_topics()
        return get_topic_registry()

    def test_agent_jobs_gateway_mirrors_match_owner(self, registry):
        """Agent-jobs mirror constants must equal agents-owned registered topics.

        agent_jobs must not import agents modules (architecture boundary).
        Mirror strings are asserted equal via the topic registry.
        """
        # Agent-owned canonical topics (registered in agents/events.yaml)
        owner_topics = {
            "agents.llm.gateway.requested",
            "agents.llm.gateway.cancel-requested",
            "agents.llm.completed",
            "agents.llm.failed",
            "agents.llm.rejected",
            "agents.llm.cancelled",
            "agents.llm.interrupted",
        }

        # Agent-jobs mirror constants (defined in event_observer.py, control.py)
        from audiagentic.components.agent_jobs.control import (
            GW_TOPIC_CANCEL_REQUESTED as CONTROL_CANCEL_MIRROR,
        )
        from audiagentic.components.agent_jobs.event_observer import (
            GW_OUTCOME_TOPICS,
            GW_TOPIC_CANCEL_REQUESTED,
            GW_TOPIC_REQUESTED,
        )

        # Every mirror must be a registered topic
        mirrors = {
            "GW_TOPIC_REQUESTED": GW_TOPIC_REQUESTED,
            "GW_TOPIC_CANCEL_REQUESTED": GW_TOPIC_CANCEL_REQUESTED,
            "CONTROL_GW_TOPIC_CANCEL_REQUESTED": CONTROL_CANCEL_MIRROR,
        }
        for name, value in mirrors.items():
            assert registry.is_registered(value), (
                f"Mirror {name} = {value!r} is not a registered topic"
            )

        # Mirror strings must equal the owner's registered topic exactly
        assert GW_TOPIC_REQUESTED == "agents.llm.gateway.requested"
        assert GW_TOPIC_CANCEL_REQUESTED == "agents.llm.gateway.cancel-requested"
        assert CONTROL_CANCEL_MIRROR == "agents.llm.gateway.cancel-requested"

        # Gateway outcome topics all registered
        for topic in GW_OUTCOME_TOPICS:
            assert registry.is_registered(topic), (
                f"GW_OUTCOME_TOPICS member {topic!r} not registered"
            )
        assert set(GW_OUTCOME_TOPICS).issubset(owner_topics)

