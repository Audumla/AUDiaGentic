"""Unit tests for agents_gateway_profiles — snapshot and digest helpers (SH07 C2, AS105/AS101)."""
from __future__ import annotations

import pytest

from audiagentic.components.agents.gateway import profiles as profiles_mod
from audiagentic.foundation.contracts.errors import AudiaGenticError


class TestStripSecrets:
    def test_removes_known_secret_keys(self):
        params = {
            "virtual-capacity": 2,
            "api-key": "sk-12345",
            "model_id": "gpt-4",
            "token": "tok_abc",
        }
        stripped = profiles_mod._strip_secrets(params)
        assert "api-key" not in stripped
        assert "token" not in stripped
        assert "virtual-capacity" in stripped
        assert "model_id" in stripped

    def test_preserves_non_secret_params(self):
        params = {
            "virtual-capacity": 2,
            "temperature": 0.7,
            "provider_id": "openai",
        }
        stripped = profiles_mod._strip_secrets(params)
        assert stripped == params

    def test_empty_params(self):
        assert profiles_mod._strip_secrets({}) == {}


class TestConfigDigest:
    def test_deterministic_for_same_params(self):
        params_a = {"virtual-capacity": 2, "model_id": "gpt-4", "provider_id": "openai"}
        params_b = {"provider_id": "openai", "virtual-capacity": 2, "model_id": "gpt-4"}
        digest_a = profiles_mod._config_digest(params_a)
        digest_b = profiles_mod._config_digest(params_b)
        assert digest_a == digest_b

    def test_different_when_params_differ(self):
        params_a = {"virtual-capacity": 2, "provider_id": "openai"}
        params_b = {"virtual-capacity": 3, "provider_id": "openai"}
        assert profiles_mod._config_digest(params_a) != profiles_mod._config_digest(params_b)

    def test_secrets_dont_affect_digest(self):
        params_a = {"virtual-capacity": 2, "provider_id": "openai"}
        params_b = {"virtual-capacity": 2, "provider_id": "openai", "api-key": "sk-12345"}
        assert profiles_mod._config_digest(params_a) == profiles_mod._config_digest(params_b)

    def test_format_has_sha256_prefix(self):
        digest = profiles_mod._config_digest({"model_id": "m"})
        assert digest.startswith("sha256:")


class TestResolvedExecutionProfile:
    def test_resolved_surface_fields_default_to_none(self):
        snapshot = profiles_mod.ResolvedExecutionProfile(
            profile_id="p", generation="g", config_digest="d", provider_id="local",
            instances=("m",), execution_params={},
        )
        assert snapshot.resolved_surface_id is None
        assert snapshot.resolved_surface_version is None
        assert snapshot.to_mapping()["resolved-surface-id"] is None
        assert snapshot.to_mapping()["instances"] == ["m"]

    def test_resolved_surface_fields_pass_schema_validation(self):
        snapshot = profiles_mod.ResolvedExecutionProfile(
            profile_id="p", generation="g", config_digest="d", provider_id="pi",
            instances=("m",), execution_params={},
            resolved_surface_id="pi-community-acp", resolved_surface_version="1.0",
        )
        assert snapshot.to_mapping()["resolved-surface-id"] == "pi-community-acp"
        assert snapshot.to_mapping()["resolved-surface-version"] == "1.0"

    def test_multiple_instances_pass_schema_validation(self):
        snapshot = profiles_mod.ResolvedExecutionProfile(
            profile_id="p", generation="g", config_digest="d", provider_id="local",
            instances=("m27b1", "m27b2"), execution_params={},
        )
        assert snapshot.to_mapping()["instances"] == ["m27b1", "m27b2"]


class TestSnapshotFromResolvedProfile:
    def test_same_params_produce_same_generation(self):
        params = {"virtual-capacity": 1, "provider_id": "local", "model_id": "m"}
        snap_a = profiles_mod.snapshot_from_resolved_profile(
            profile_id="p", provider_id=params["provider_id"], instances=("m",), params=params,
        )
        snap_b = profiles_mod.snapshot_from_resolved_profile(
            profile_id="p", provider_id=params["provider_id"], instances=("m",), params=dict(params),
        )
        assert snap_a.generation == snap_b.generation
        assert snap_a.config_digest == snap_b.config_digest

    def test_different_params_produce_different_generation(self):
        base = {"provider_id": "local"}
        snap_a = profiles_mod.snapshot_from_resolved_profile(
            profile_id="p", provider_id=base["provider_id"], instances=("m",), params={**base, "virtual-capacity": 1},
        )
        snap_b = profiles_mod.snapshot_from_resolved_profile(
            profile_id="p", provider_id=base["provider_id"], instances=("m",), params={**base, "virtual-capacity": 2},
        )
        assert (snap_a.generation, snap_a.config_digest) != (snap_b.generation, snap_b.config_digest)

    def test_secrets_not_in_execution_params(self):
        params = {"provider_id": "local", "model_id": "m", "api-key": "sk-secret"}
        snapshot = profiles_mod.snapshot_from_resolved_profile(
            profile_id="p", provider_id=params["provider_id"], instances=("m",), params=params,
        )
        # execution_params is a MappingProxyType; iterate over it
        for k in snapshot.execution_params:
            assert "api-key" not in k.lower()

    def test_instances_carried_through_unchanged(self):
        snap = profiles_mod.snapshot_from_resolved_profile(
            profile_id="p", provider_id="local", instances=("m27b1", "m27b2"), params={},
        )
        assert snap.instances == ("m27b1", "m27b2")


def _make_resolved_surface(*, validated: bool, surface_id: str = "pi-community-acp", resolved_version: str = "1.0"):
    from audiagentic.foundation.transports.session_surface import (
        ResolvedSessionSurface,
        SessionIdentityCapabilities,
        SessionSurfaceRef,
        SurfaceValidation,
        ValidationEvidence,
    )

    return ResolvedSessionSurface(
        ref=SessionSurfaceRef(provider_id="pi", surface_id=surface_id, resolved_version=resolved_version),
        identity=SessionIdentityCapabilities(),
        validation=SurfaceValidation(
            evidence=ValidationEvidence(validated=validated, reference="test" if validated else "")
        ),
    )


class TestResolveForAdmissionSurface:
    """AS82: surface_id resolution at the admission boundary."""

    def _profile(self, project_root, *, surface_id=None):
        from audiagentic.components.agents.models.execution_profile_api import (
            create_execution_profile,
        )
        create_execution_profile(
            project_root,
            {
                "profile_id": "with-surface",
                "provider_id": "pi",
                "instances": ["m"],
                **({"surface_id": surface_id} if surface_id else {}),
            },
        )

    def test_missing_shared_registry_fails_closed(self, tmp_path):
        from audiagentic.components.agents.models.execution_profile_api import (
            create_execution_profile,
        )

        create_execution_profile(
            tmp_path,
            {"profile_id": "registry-required", "provider_id": "pi", "instances": ["m"]},
        )
        profiles_mod.set_gateway_registry(None)
        with pytest.raises(AudiaGenticError, match="shared gateway profile registry"):
            profiles_mod.resolve_for_admission(tmp_path, "registry-required")

    def test_no_surface_id_resolves_unchanged(self, tmp_path):
        self._profile(tmp_path)
        snapshot = profiles_mod.resolve_for_admission(tmp_path, "with-surface", allow_test_fallback=True)
        assert snapshot.resolved_surface_id is None
        assert snapshot.resolved_surface_version is None

    def test_validated_surface_carries_identity_into_snapshot(self, tmp_path):
        self._profile(tmp_path, surface_id="pi-community-acp")
        calls = []

        def fake_resolver(project_root, provider_id, surface_id):
            calls.append((project_root, provider_id, surface_id))
            return _make_resolved_surface(validated=True, surface_id=surface_id)

        snapshot = profiles_mod.resolve_for_admission(
            tmp_path, "with-surface", surface_resolver=fake_resolver, allow_test_fallback=True
        )
        assert snapshot.resolved_surface_id == "pi-community-acp"
        assert snapshot.resolved_surface_version == "1.0"
        assert calls == [(tmp_path, "pi", "pi-community-acp")]

    def test_unvalidated_surface_raises_res_exp_004_before_dispatch(self, tmp_path):
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        self._profile(tmp_path, surface_id="unknown-surface")

        def fake_resolver(project_root, provider_id, surface_id):
            return _make_resolved_surface(validated=False, surface_id=surface_id)

        with pytest.raises(AudiaGenticError) as exc_info:
            profiles_mod.resolve_for_admission(tmp_path, "with-surface", surface_resolver=fake_resolver, allow_test_fallback=True)
        assert exc_info.value.code == "RES-EXP-004"
        assert exc_info.value.kind == "agents"

    def test_unvalidated_surface_never_falls_back_to_provider_default(self, tmp_path):
        """An explicitly named surface that fails validation must raise, not
        silently return a snapshot with no resolved surface (the provider
        default shape) -- that would be a silent degrade."""
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        self._profile(tmp_path, surface_id="unknown-surface")

        def fake_resolver(project_root, provider_id, surface_id):
            return _make_resolved_surface(validated=False, surface_id=surface_id)

        try:
            profiles_mod.resolve_for_admission(tmp_path, "with-surface", surface_resolver=fake_resolver, allow_test_fallback=True)
        except AudiaGenticError:
            pass
        else:
            pytest.fail("expected RES-EXP-004, got a silent fallback snapshot")

    def test_resolution_launches_no_process(self, tmp_path):
        """Resolution is a read: fake asserts it is never asked to open/prompt."""
        self._profile(tmp_path, surface_id="pi-community-acp")

        class _NoLaunchFake:
            def __call__(self, project_root, provider_id, surface_id):
                return _make_resolved_surface(validated=True, surface_id=surface_id)

            def open(self, *a, **k):
                raise AssertionError("resolve_for_admission must not open a session")

            def prompt(self, *a, **k):
                raise AssertionError("resolve_for_admission must not prompt")

        fake = _NoLaunchFake()
        profiles_mod.resolve_for_admission(tmp_path, "with-surface", surface_resolver=fake, allow_test_fallback=True)

    def test_project_local_agents_catalog_is_ignored(self, tmp_path):
        """Agent admission must not be shadowed by a project-local catalog."""
        from audiagentic.components.agents.models.execution_profile_api import (
            create_execution_profile,
        )

        create_execution_profile(
            tmp_path,
            {
                "profile_id": "global-only",
                "provider_id": "pi",
                "instances": ["global-model"],
            },
        )
        local = tmp_path / ".audiagentic" / "config" / "agents.yaml"
        local.parent.mkdir(parents=True)
        local.write_text(
            "contract-version: v2\nexecution_profiles:\n"
            "  local-only:\n    provider_id: local-openai\n    instances: [wrong]\n",
            encoding="utf-8",
        )

        snapshot = profiles_mod.resolve_for_admission(tmp_path, "global-only", allow_test_fallback=True)
        assert snapshot.provider_id == "pi"
        assert snapshot.instances == ("global-model",)


class TestInMemoryExecutionProfileRegistry:

    def test_resolve_snapshot(self):
        reg = profiles_mod.InMemoryExecutionProfileRegistry()
        reg.register("gw-profile", provider_id="local", instances=("m",))
        snap = reg.resolve_snapshot("gw-profile")
        assert snap.profile_id == "gw-profile"
        assert snap.provider_id == "local"
        assert snap.instances == ("m",)

    def test_not_found_raises(self):
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        reg = profiles_mod.InMemoryExecutionProfileRegistry()
        with pytest.raises(AudiaGenticError) as exc_info:
            reg.resolve_snapshot("nonexistent")
        assert exc_info.value.code == "RES-EXP-001"

    def test_re_register_changes_generation(self):
        """Re-registering the same profile with different content changes the
        content-derived generation."""
        reg = profiles_mod.InMemoryExecutionProfileRegistry()
        reg.register("gw-profile", provider_id="local", instances=("m",))
        snap_v1 = reg.resolve_snapshot("gw-profile")

        reg.register("gw-profile", provider_id="local", instances=("m27b1", "m27b2"))
        snap_v2 = reg.resolve_snapshot("gw-profile")

        assert snap_v1.generation != snap_v2.generation, "re-register must change generation"
        assert snap_v2.instances == ("m27b1", "m27b2")

    def test_validate_current_after_change(self):
        """Snapshot from old generation is stale after re-register."""
        reg = profiles_mod.InMemoryExecutionProfileRegistry()
        reg.register("gw-profile", provider_id="local", instances=("m",))
        snap_v1 = reg.resolve_snapshot("gw-profile")

        assert reg.validate_snapshot_current(snap_v1) is True

        reg.register("gw-profile", provider_id="local", instances=("m27b1", "m27b2"))
        assert reg.validate_snapshot_current(snap_v1) is False, "old snapshot must be stale"

    def test_secrets_stripped_from_snapshot(self):
        """Secret params are stripped from the gateway snapshot."""
        reg = profiles_mod.InMemoryExecutionProfileRegistry()
        reg.register(
            "gw-profile",
            provider_id="local",
            instances=("m",),
            execution_params={"api-key": "sk-secret", "temperature": 0.7},
        )
        snap = reg.resolve_snapshot("gw-profile")
        for k in snap.execution_params:
            assert "api-key" not in k.lower()

    def test_snapshot_from_record(self):
        """Reconstruct snapshot from persisted record fields."""
        reg = profiles_mod.InMemoryExecutionProfileRegistry()
        reg.register("test-profile", provider_id="local", instances=("m27b1", "m27b2"))
        snap = reg.resolve_snapshot("test-profile")

        record = {
            "gateway-profile-id": snap.profile_id,
            "gateway-profile-generation": snap.generation,
            "gateway-profile-config-digest": snap.config_digest,
            "resolved-provider-id": snap.provider_id,
            "resolved-instance-ids": list(snap.instances),
        }
        reconstructed = profiles_mod.snapshot_from_record(record)
        assert reconstructed is not None
        assert reconstructed.profile_id == snap.profile_id
        assert reconstructed.generation == snap.generation
        assert reconstructed.instances == ("m27b1", "m27b2")

    def test_snapshot_from_record_missing_fields(self):
        """Pre-SH07 C2 record without snapshot fields returns None (embedded mode)."""
        record = {"execution-profile-id": "old-profile"}
        assert profiles_mod.snapshot_from_record(record) is None

    def test_snapshot_from_record_pre_pivot_shape_raises_val_exp_006(self):
        """AS105/AS101 decided fail-mode: a record admitted under a
        shared-gateway snapshot before the free-instance dispatch pivot has
        gateway-profile-id but no resolved-instance-ids -- fail closed
        rather than silently misparse it as an empty instance set."""
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        record = {
            "request-id": "req_old",
            "gateway-profile-id": "test-profile",
            "gateway-profile-generation": "gen_old",
            "gateway-profile-config-digest": "sha256:old",
            "resolved-provider-id": "local",
            "resolved-model-id": "m",
        }
        with pytest.raises(AudiaGenticError) as exc_info:
            profiles_mod.snapshot_from_record(record)
        assert exc_info.value.code == "VAL-EXP-006"
