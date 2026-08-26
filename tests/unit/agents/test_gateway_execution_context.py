"""SH02 exit-gate tests for the execution-context contract (five families)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.agents.contracts.execution_context import (
    ExecutionManifest,
    ManifestIdentity,
    SubmissionEnvelope,
    build_manifest,
    canonicalize_project_root,
    compute_agent_runtime_digest,
    compute_context_fingerprint,
    compute_prompt_digest,
    derive_idempotency_key,
    fingerprint_form,
    sanitize_submission_metadata,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _envelope(tmp_path: Path, **overrides) -> SubmissionEnvelope:
    values = {
        "project_root": str(tmp_path),
        "execution_profile_id": "deep-coder-opencode",
        "prompt_body": "implement the thing",
        "session": {"session_id": None, "keep_alive": False},
    }
    values.update(overrides)
    return SubmissionEnvelope.from_mapping(values)


def _identity(**overrides) -> ManifestIdentity:
    values = {
        "project_root": "h:/projects/a",
        "execution_profile_id": "deep-coder-opencode",
        "provider_id": "opencode",
        "model_id": "brutus/coder-quality-mid",
        "provider_isolation_tier": "partial-isolation",
        "component_profile": "",
        "agent_runtime_digest": "d" * 64,
    }
    values.update(overrides)
    return ManifestIdentity(**values)


# --- family 1: path round-trips -------------------------------------------


class TestPathCanonicalization:
    def test_windows_spellings_share_one_fingerprint(self, tmp_path: Path) -> None:
        base = canonicalize_project_root(tmp_path, windows=True)
        variants = [
            str(tmp_path).upper(),
            str(tmp_path).lower(),
            str(tmp_path) + "\\",
            str(tmp_path).replace("\\", "/"),
        ]
        for variant in variants:
            assert canonicalize_project_root(variant, windows=True).fingerprint == base.fingerprint

    def test_posix_form_preserves_case_and_normalizes_nfc(self) -> None:
        assert fingerprint_form("/home/User/proj", windows=False) != fingerprint_form(
            "/home/user/proj", windows=False
        )
        composed = "/home/café"
        decomposed = "/home/café"
        assert fingerprint_form(composed, windows=False) == fingerprint_form(decomposed, windows=False)

    def test_relative_root_rejected(self) -> None:
        with pytest.raises(AudiaGenticError) as exc:
            canonicalize_project_root("relative/dir")
        assert exc.value.code == "VAL-AGW-062"

    def test_unc_root_rejected(self) -> None:
        with pytest.raises(AudiaGenticError) as exc:
            canonicalize_project_root("\\\\server\\share\\proj")
        assert exc.value.code == "VAL-AGW-064"

    def test_symlink_free_resolution_round_trips(self, tmp_path: Path) -> None:
        root = canonicalize_project_root(tmp_path)
        assert Path(root.display).exists()
        assert root.fingerprint == canonicalize_project_root(root.display).fingerprint


# --- family 2: fingerprint and idempotency determinism ---------------------


class TestDeterminism:
    def test_identical_identity_yields_identical_fingerprint(self) -> None:
        assert compute_context_fingerprint(_identity()) == compute_context_fingerprint(_identity())

    @pytest.mark.parametrize(
        "change",
        [
            {"model_id": "brutus/coder-quality-lite"},
            {"component_profile": "bench"},
            {"agent_runtime_digest": "e" * 64},
            {"provider_isolation_tier": "no-isolation"},
            {"project_root": "h:/projects/b"},
        ],
    )
    def test_identity_change_changes_fingerprint(self, change: dict) -> None:
        assert compute_context_fingerprint(_identity(**change)) != compute_context_fingerprint(_identity())

    def test_runtime_digest_ignores_key_order_but_not_values(self) -> None:
        profile = {"profile_id": "p", "params": {"retry-count": 0}}
        base = compute_agent_runtime_digest(profile, {"mcp": ["a"]}, {})
        reordered = compute_agent_runtime_digest(
            dict(reversed(list(profile.items()))), {"mcp": ["a"]}, {}
        )
        changed = compute_agent_runtime_digest(profile, {"mcp": ["a", "b"]}, {})
        assert base == reordered
        assert base != changed

    def test_derived_idempotency_key_is_unique_and_client_key_wins(self) -> None:
        # SH review C8: no explicit key means a fresh request every time —
        # identical repeated prompts are separate turns, never silent replays.
        first = derive_idempotency_key(
            None, context_fingerprint="f" * 64, prompt_digest="p" * 64, session_id=None
        )
        second = derive_idempotency_key(
            None, context_fingerprint="f" * 64, prompt_digest="p" * 64, session_id=None
        )
        assert first != second
        assert (
            derive_idempotency_key(
                "client-key", context_fingerprint="f" * 64, prompt_digest="p" * 64, session_id=None
            )
            == "client-key"
        )


# --- family 3: cross-project bleed -----------------------------------------


class TestCrossProjectIsolation:
    def test_conflicting_projects_share_no_identity(self, tmp_path: Path) -> None:
        root_a = tmp_path / "project-a"
        root_b = tmp_path / "project-b"
        root_a.mkdir()
        root_b.mkdir()
        manifests = []
        for root, profile, digest in (
            (root_a, "profile-a", "a" * 64),
            (root_b, "profile-b", "b" * 64),
        ):
            envelope = _envelope(tmp_path, project_root=str(root), execution_profile_id=profile)
            manifests.append(
                build_manifest(
                    envelope,
                    manifest_id="m",
                    request_id="r",
                    resolved_at="2026-07-17T00:00:00Z",
                    canonical_root=envelope.validate(),
                    execution_profile_id=profile,
                    provider_id="opencode",
                    model_id="brutus/coder-quality-mid",
                    provider_isolation_tier="partial-isolation",
                    agent_runtime_digest=digest,
                )
            )
        a, b = manifests
        assert a.context_fingerprint != b.context_fingerprint
        assert a.identity.project_root != b.identity.project_root
        assert a.identity.agent_runtime_digest != b.identity.agent_runtime_digest

    def test_identity_fields_are_a_closed_set(self) -> None:
        assert set(_identity().to_mapping()) == {
            "project_root",
            "execution_profile_id",
            "provider_id",
            "model_id",
            "provider_isolation_tier",
            "component_profile",
            "agent_runtime_digest",
        }


# --- family 4: redaction ----------------------------------------------------


class TestRedaction:
    def test_manifest_never_carries_prompt_body(self, tmp_path: Path) -> None:
        secret_prompt = "the launch code is sk-AAAABBBBCCCCDDDDEEEE"
        envelope = _envelope(tmp_path, prompt_body=secret_prompt)
        manifest = build_manifest(
            envelope,
            manifest_id="m",
            request_id="r",
            resolved_at="2026-07-17T00:00:00Z",
            canonical_root=envelope.validate(),
            execution_profile_id="deep-coder-opencode",
            provider_id="opencode",
            model_id="brutus/coder-quality-mid",
            provider_isolation_tier="partial-isolation",
            agent_runtime_digest="d" * 64,
        )
        dumped = json.dumps(manifest.to_mapping())
        assert secret_prompt not in dumped
        assert "sk-AAAA" not in dumped
        assert manifest.prompt_digest == compute_prompt_digest(secret_prompt)

    @pytest.mark.parametrize(
        "value",
        [
            "sk-AAAABBBBCCCCDDDDEEEE",
            "AKIAABCDEFGHIJKLMNOP",
            "Bearer abcdefghijklmnop.qrstuvwxyz",
            "-----BEGIN RSA PRIVATE KEY-----",
        ],
    )
    def test_credential_material_in_metadata_rejected(self, tmp_path: Path, value: str) -> None:
        envelope = _envelope(tmp_path, metadata={"note": value})
        with pytest.raises(AudiaGenticError) as exc:
            envelope.validate()
        assert exc.value.code == "VAL-AGW-065"

    def test_prompt_content_is_not_canary_scanned(self, tmp_path: Path) -> None:
        envelope = _envelope(tmp_path, prompt_body="rotate the key sk-AAAABBBBCCCCDDDDEEEE")
        envelope.validate()  # must not raise


# --- family 5: version negotiation and validation ---------------------------


class TestVersionNegotiation:
    @pytest.mark.parametrize("version", [0, 3, 99])
    def test_unsupported_version_yields_stable_error(self, tmp_path: Path, version: int) -> None:
        envelope = _envelope(tmp_path, schema_version=version)
        with pytest.raises(AudiaGenticError) as exc:
            envelope.validate()
        assert exc.value.code == "VAL-AGW-069"
        assert exc.value.details["requested"] == version
        assert exc.value.details["supported_min"] == 1

    def test_provider_without_model_rejected(self, tmp_path: Path) -> None:
        envelope = _envelope(tmp_path, provider_id="opencode")
        with pytest.raises(AudiaGenticError) as exc:
            envelope.validate()
        assert exc.value.code == "VAL-AGW-063"

    def test_invalid_mode_rejected(self, tmp_path: Path) -> None:
        envelope = _envelope(tmp_path, mode="fire-and-forget")
        with pytest.raises(AudiaGenticError) as exc:
            envelope.validate()
        assert exc.value.code == "VAL-AGW-066"

    def test_invalid_isolation_tier_rejected(self) -> None:
        with pytest.raises(AudiaGenticError) as exc:
            _identity(provider_isolation_tier="sometimes")
        assert exc.value.code == "VAL-AGW-067"

    def test_envelope_and_manifest_round_trip(self, tmp_path: Path) -> None:
        envelope = _envelope(tmp_path, idempotency_key="idem-1", correlation_id="corr-1")
        assert SubmissionEnvelope.from_mapping(envelope.to_mapping()) == envelope
        manifest = build_manifest(
            envelope,
            manifest_id="m",
            request_id="r",
            resolved_at="2026-07-17T00:00:00Z",
            canonical_root=envelope.validate(),
            execution_profile_id="deep-coder-opencode",
            provider_id="opencode",
            model_id="brutus/coder-quality-mid",
            provider_isolation_tier="partial-isolation",
            agent_runtime_digest="d" * 64,
        )
        restored = ExecutionManifest.from_mapping(json.loads(json.dumps(manifest.to_mapping())))
        assert restored == manifest
        assert restored.context_fingerprint == compute_context_fingerprint(restored.identity)


class TestSubmissionWireValidation:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("schema_version", "1"),
            ("idempotency_key", 7),
            ("idempotency_key", "x" * 513),
            ("timeout_seconds", "later"),
            ("timeout_seconds", 0),
            ("timeout_seconds", float("inf")),
            ("mode", True),
            ("prompt_body", 123),
        ],
    )
    def test_scalar_wire_values_fail_with_canonical_error(
        self, tmp_path: Path, field: str, value: object
    ) -> None:
        envelope = _envelope(tmp_path, **{field: value})
        with pytest.raises(AudiaGenticError) as exc:
            envelope.validate()
        assert exc.value.code == "VAL-AGW-082"
        assert exc.value.details["field"] == field

    def test_session_and_metadata_wire_shapes_fail_with_canonical_error(self, tmp_path: Path) -> None:
        with pytest.raises(AudiaGenticError, match="VAL-AGW-082"):
            SubmissionEnvelope.from_mapping({"project_root": str(tmp_path), "session": []})
        envelope = _envelope(tmp_path, metadata={"note": object()})
        with pytest.raises(AudiaGenticError, match="VAL-AGW-082"):
            envelope.validate()

    def test_reserved_metadata_aliases_are_removed_recursively(self) -> None:
        prompt_canary = "METADATA_SECRET_PROMPT"
        idempotency_canary = "RAW_KEY_ALIAS"
        sanitized = sanitize_submission_metadata(
            {
                "correlation_id": "corr-123",
                "subject": {"kind": "test"},
                "prompt_body": prompt_canary,
                "nested": [{"idempotencyKey": idempotency_canary, "safe": "kept"}],
            }
        )
        encoded = json.dumps(sanitized)
        assert prompt_canary not in encoded
        assert idempotency_canary not in encoded
        assert sanitized["correlation_id"] == "corr-123"
        assert sanitized["subject"] == {"kind": "test"}
        assert sanitized["nested"] == [{"safe": "kept"}]
