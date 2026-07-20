"""AS33 capability-snapshot projection contract guard (unit).

Tests verify: absent-when-unresolved, redaction of forbidden keys, whitelist
projection only, static guard against risky key names in projected output,
and that the helper does not infer capabilities from provider/surface identity.
"""
from __future__ import annotations

from audiagentic.components.agents import agents_gateway_session_bindings as binding_store


class TestProjectSessionCapabilitiesAbsentWhenUnresolved:
    """No snapshot means no capabilities key."""

    def test_none_input(self):
        assert binding_store.project_session_capabilities(None) is None

    def test_empty_dict_input(self):
        assert binding_store.project_session_capabilities({}) is None

    def test_no_snapshot_key(self):
        record = {"session-id": "ses_1", "state": "active"}
        assert binding_store.project_session_capabilities(record) is None

    def test_empty_snapshot_value(self):
        record = {"capability-snapshot": {}}
        assert binding_store.project_session_capabilities(record) is None

    def test_non_dict_snapshot_value(self):
        record = {"resolved-capabilities": "not-a-dict"}
        assert binding_store.project_session_capabilities(record) is None


class TestProjectSessionCapabilitiesRedaction:
    """Forbidden keys never appear in the projection."""

    def test_forbidden_keys_blocked(self):
        snapshot = {
            "surface-id": "acp-session",
            "provider-session-ref": "secret-ref",
            "raw-payload": {"data": "leaked"},
            "prompt": "secret prompt",
            "output": "secret output",
            "tool-args": {"arg1": 1},
            "tool_args": {"arg2": 2},
            "tool-calls": ["call1"],
            "tool_calls": ["call2"],
            "tool-arguments": {},
            "provider-surface": "native",
            "surface-ref": "native-ref",
            "native-ref": "native-id",
        }
        record = {"capability-snapshot": snapshot}
        projected = binding_store.project_session_capabilities(record)

        assert projected is not None
        assert projected.get("surface-id") == "acp-session"
        # Forbidden keys must not appear
        for forbidden_key in binding_store._CAPABILITIES_FORBIDDEN_KEYS:
            assert (
                forbidden_key not in projected
            ), f"Forbidden key '{forbidden_key}' leaked through projection"

    def test_unrecognized_keys_dropped(self):
        snapshot = {
            "surface-id": "acp-session",
            "unknown-field": "should be dropped",
            "__dangerous__": "injected",
        }
        record = {"capability-snapshot": snapshot}
        projected = binding_store.project_session_capabilities(record)

        assert projected is not None
        assert "surface-id" in projected
        assert "unknown-field" not in projected
        assert "__dangerous__" not in projected

    def test_complex_values_redacted(self):
        """Non-scalar values are recursively redacted to safe scalars."""
        snapshot = {
            "declared-controls": ["control1", 42, True, None],
            "supported-statuses": {"status1", "status2"},  # set drops entirely
            "surface-id": "acp-session",
        }
        record = {"resolved-capabilities": snapshot}
        projected = binding_store.project_session_capabilities(record)

        assert projected is not None
        # declared-controls: safe scalars (str, int, bool) pass; None drops
        dc = projected.get("declared-controls")
        assert dc is not None
        assert "control1" in dc
        assert 42 in dc  # int is a safe scalar and passes through
        assert True in dc  # bool is a safe scalar and passes through
        # supported-statuses was a set, so it redacts to None and drops
        assert "supported-statuses" not in projected

    def test_safe_scalar_values_pass_through(self):
        snapshot = {
            "surface-id": "acp-session",
            "surface-version": "1.0",
            "observation-mechanism": "direct",
            "evidence-tier": "verified",
        }
        record = {"session-capabilities": snapshot}
        projected = binding_store.project_session_capabilities(record)

        assert projected is not None
        assert projected["surface-id"] == "acp-session"
        assert projected["surface-version"] == "1.0"
        assert projected["observation-mechanism"] == "direct"
        assert projected["evidence-tier"] == "verified"


class TestProjectSessionCapabilitiesNoInference:
    """The helper must not infer capabilities from provider/surface identity."""

    def test_provider_id_not_in_output(self):
        snapshot = {
            "provider-id": "local-openai",
            "model-id": "gpt-4o",
            "surface-id": "acp-session",
        }
        record = {"capability-snapshot": snapshot}
        projected = binding_store.project_session_capabilities(record)

        assert projected is not None
        # provider-id and model-id are NOT in the safe keys whitelist
        assert "provider-id" not in projected
        assert "model-id" not in projected

    def test_surface_id_only_from_explicit_snapshot(self):
        """surface-id appears only because it was explicitly in the snapshot,
        not because it was inferred from the provider."""
        snapshot = {
            "surface-id": "acp-session",
        }
        record = {"capability-snapshot": snapshot}
        projected = binding_store.project_session_capabilities(record)

        assert projected is not None
        assert projected["surface-id"] == "acp-session"

    def test_no_snapshot_means_no_inference(self):
        """Without a snapshot, the helper cannot and must not infer anything."""
        record = {
            "session-id": "ses_1",
            "agent-profile-id": "profile-1",
            "provider-id": "local-openai",
        }
        assert binding_store.project_session_capabilities(record) is None


class TestStaticContractGuard:
    """Static/grep-style guard: projected keys must never include risky names."""

    def test_projected_keys_subset_of_safe_keys(self):
        """Any key that appears in a projection must be in the safe whitelist."""
        # Populate snapshot with every possible key including extras
        snapshot = {**dict.fromkeys(binding_store._CAPABILITIES_SAFE_KEYS, "val")}
        # Add some extra keys to simulate malicious injection
        for i in range(10):
            snapshot[f"extra_{i}"] = f"value_{i}"

        record = {"capability-snapshot": snapshot}
        projected = binding_store.project_session_capabilities(record)

        assert projected is not None
        for key in projected:
            assert (
                key in binding_store._CAPABILITIES_SAFE_KEYS
            ), f"Key '{key}' not in safe whitelist"

    def test_forbidden_keys_and_safe_keys_disjoint(self):
        """The forbidden set and safe set must not overlap."""
        intersection = (
            binding_store._CAPABILITIES_FORBIDDEN_KEYS
            & binding_store._CAPABILITIES_SAFE_KEYS
        )
        assert not intersection, (
            f"Forbidden and safe key sets overlap: {intersection}"
        )

    def test_repr_has_no_forbidden_key_names(self):
        """The repr of a projection must not contain forbidden key names."""
        snapshot = {
            "surface-id": "acp-session",
            "provider-session-ref": "hidden",
            "prompt": "hidden",
        }
        record = {"capability-snapshot": snapshot}
        projected = binding_store.project_session_capabilities(record)
        repr_str = repr(projected)

        for forbidden in binding_store._CAPABILITIES_FORBIDDEN_KEYS:
            assert (
                forbidden not in repr_str
            ), f"Forbidden key name '{forbidden}' found in projection repr"
