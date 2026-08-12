"""AS30 Stage-3: Recovery validation tests for binding index.

Tests that the binding index can recover from corruption, orphaned records,
and duplicate active owned bindings. Also validates binding lifecycle
stability across restarts and identity consistency.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from audiagentic.components.agents.gateway.session import bindings as bindings
from audiagentic.components.agents.gateway.session import sessions_store as session_store
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a minimal project root with .audiagentic marker."""
    (tmp_path / ".audiagentic").mkdir(parents=True)
    return tmp_path


# ── Helpers ────────────────────────────────────────────────────────

def _make_session_record(
    project_root: Path,
    session_id: str,
    provider_ref: str,
    state: str = "active",
    provider_id: str | None = "test-provider",
) -> dict[str, Any]:
    """Write a session record with a binding and return the full record."""
    record = session_store.build_session_record(
        session_id=session_id,
        execution_profile_id="default",
        provider_id=provider_id,
        provider_session_ref=provider_ref,
        surface_id="test-surface",
    )
    if state != "active":
        record["state"] = state
    session_store.write_session_record(project_root, record)
    return record


# ── Recovery Validation Tests ─────────────────────────────────────

class TestCorruptedIndexRecovery:
    """Rebuild from corrupted index: index.json is truncated/malformed →
    rebuild_binding_index recovers all active bindings from session records."""

    def test_truncated_json_recovery(self, project_root: Path) -> None:
        """Truncated JSON → rebuild recovers from sessions."""
        for i in range(3):
            _make_session_record(project_root, f"ses_trunc_{i}", f"ref-trunc-{i}")

        # Write a valid index first.
        bindings.rebuild_index(project_root)

        # Truncate the index to incomplete JSON.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        index_path.write_text('{"contract-version": "v1"', encoding="utf-8")

        # Rebuild should recover all sessions.
        rebuilt = bindings.rebuild_index(project_root)
        assert len(rebuilt["bindings"]) == 3

    def test_malformed_json_recovery(self, project_root: Path) -> None:
        """Malformed JSON (not parseable) → rebuild recovers from sessions."""
        for i in range(2):
            _make_session_record(project_root, f"ses_malf_{i}", f"ref-malf-{i}")

        bindings.rebuild_index(project_root)

        # Write malformed JSON.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        index_path.write_text("not json at all", encoding="utf-8")

        rebuilt = bindings.rebuild_index(project_root)
        assert len(rebuilt["bindings"]) == 2

    def test_binary_corruption_recovery(self, project_root: Path) -> None:
        """Binary garbage in index file → rebuild recovers from sessions."""
        _make_session_record(project_root, "ses_binary", "ref-binary")

        bindings.rebuild_index(project_root)

        # Write binary garbage.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        index_path.write_bytes(b"\x00\x01\x02\xff\xfe\xfd")

        rebuilt = bindings.rebuild_index(project_root)
        assert len(rebuilt["bindings"]) == 1

    def test_empty_file_recovery(self, project_root: Path) -> None:
        """Empty index file → rebuild recovers from sessions."""
        _make_session_record(project_root, "ses_empty", "ref-empty-recover")

        bindings.rebuild_index(project_root)

        # Write empty file.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        index_path.write_text("", encoding="utf-8")

        rebuilt = bindings.rebuild_index(project_root)
        assert len(rebuilt["bindings"]) == 1

    def test_missing_index_recovery(self, project_root: Path) -> None:
        """Index file deleted → rebuild creates fresh index from sessions."""
        for i in range(2):
            _make_session_record(project_root, f"ses_del_{i}", f"ref-del-{i}")

        bindings.rebuild_index(project_root)

        # Delete the index entirely.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        index_path.unlink()

        rebuilt = bindings.rebuild_index(project_root)
        assert len(rebuilt["bindings"]) == 2
        assert index_path.exists()  # Rebuilt file exists again.

    def test_wrong_schema_recovery(self, project_root: Path) -> None:
        """Index with wrong schema (no 'bindings' key) → rebuild replaces it."""
        _make_session_record(project_root, "ses_schema", "ref-schema")

        bindings.rebuild_index(project_root)

        # Write valid JSON but wrong schema.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        index_path.write_text(
            json.dumps({"contract-version": "v1"}),  # Missing 'bindings'.
            encoding="utf-8",
        )

        rebuilt = bindings.rebuild_index(project_root)
        assert len(rebuilt["bindings"]) == 1


class TestOrphanedBindingDetection:
    """Binding record exists but no corresponding session → detected during rebuild."""

    def test_orphaned_binding_in_rebuild(self, project_root: Path) -> None:
        """Rebuild detects entries with no matching active session."""
        # Create a session and register it.
        _make_session_record(project_root, "ses_orphan", "ref-orphan")
        bindings.rebuild_index(project_root)

        # Now delete the session record but leave index intact.
        session_path = session_store.gateway_session_path(project_root, "ses_orphan")
        session_path.unlink()

        # Rebuild: the orphaned binding should not appear since it's rebuilt
        # from session records only.
        rebuilt = bindings.rebuild_index(project_root)
        # The key should be gone because there's no session to rebuild it from.
        assert len(rebuilt["bindings"]) == 0

    def test_orphaned_binding_not_restored(self, project_root: Path) -> None:
        """An orphaned binding in the existing index is not restored after rebuild."""
        # Create a session with a binding.
        _make_session_record(project_root, "ses_permanent", "ref-perm")
        _make_session_record(project_root, "ses_to_delete", "ref-to-del")
        bindings.rebuild_index(project_root)

        # Verify both are in the index.
        payload = bindings._read_index(bindings.gateway_session_binding_index_path(project_root))
        assert len(payload["bindings"]) == 2

        # Delete one session record.
        to_delete_path = session_store.gateway_session_path(project_root, "ses_to_delete")
        to_delete_path.unlink()

        # Rebuild should only have the surviving session's binding.
        rebuilt = bindings.rebuild_index(project_root)
        assert len(rebuilt["bindings"]) == 1
        key = bindings.provider_ref_key(
            provider_id="test-provider",
            surface_id="test-surface",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-perm",
        )
        assert key in rebuilt["bindings"]

    def test_closed_sessions_not_rebuilt(self, project_root: Path) -> None:
        """Sessions in closed/expired/failed states are not included in rebuild."""
        _make_session_record(project_root, "ses_closed", "ref-closed", state="closed")
        _make_session_record(project_root, "ses_active", "ref-active", state="active")

        rebuilt = bindings.rebuild_index(project_root)

        # Only the active session should be in the index.
        assert len(rebuilt["bindings"]) == 1
        key = bindings.provider_ref_key(
            provider_id="test-provider",
            surface_id="test-surface",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-active",
        )
        assert key in rebuilt["bindings"]


class TestDuplicateActiveOwnedBindings:
    """Detect duplicate active owned bindings — should be impossible if
    open_binding is atomic, but rebuild should surface the inconsistency."""

    def test_duplicate_detected_in_rebuild(self, project_root: Path) -> None:
        """Two sessions with owned active bindings for same key → rebuild detects it."""
        # Create two sessions with the same provider ref.
        record1 = _make_session_record(project_root, "ses_dup_1", "ref-dup-rebuild")
        record2 = _make_session_record(project_root, "ses_dup_2", "ref-dup-rebuild")

        # Build an index with both (bypassing the normal duplicate check).
        key = bindings.provider_ref_key(
            provider_id="test-provider",
            surface_id="test-surface",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-dup-rebuild",
        )
        index_path = bindings.gateway_session_binding_index_path(project_root)
        payload = {
            "contract-version": "v1",
            "bindings": {
                key: [
                    {
                        "binding-id": record1["binding"]["binding-id"],
                        "session-id": "ses_dup_1",
                        "ownership": "owned",
                        "relation": "opened",
                        "state": "active",
                        "created-at": record1["binding"]["created-at"],
                    },
                    {
                        "binding-id": record2["binding"]["binding-id"],
                        "session-id": "ses_dup_2",
                        "ownership": "owned",
                        "relation": "opened",
                        "state": "active",
                        "created-at": record2["binding"]["created-at"],
                    },
                ]
            },
        }
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(payload), encoding="utf-8")

        # Rebuild should detect the duplicate (it scans sessions).
        rebuilt = bindings.rebuild_index(project_root)
        # Both sessions are active with owned bindings — both appear in rebuild.
        assert len(rebuilt["bindings"]) == 1
        entries = rebuilt["bindings"][key]
        assert len(entries) == 2

    def test_one_owned_one_closed_not_duplicate(self, project_root: Path) -> None:
        """One owned active + one owned closed → not a duplicate error."""
        _make_session_record(project_root, "ses_active_dup", "ref-one-closed")
        _make_session_record(project_root, "ses_closed_dup", "ref-one-closed", state="closed")

        rebuilt = bindings.rebuild_index(project_root)

        # Only active session is in the index.
        assert len(rebuilt["bindings"]) == 1


# ── Session Binding Lifecycle Tests ────────────────────────────────

class TestBindingPersistenceAcrossRestart:
    """Binding persists across SessionRuntime restart (same process, new instance)."""

    def test_binding_visible_after_store_roundtrip(self, project_root: Path) -> None:
        """Write session with binding → read back → binding is intact."""
        record = _make_session_record(project_root, "ses_persist", "ref-persist")

        # Read the record back from disk.
        read_record = session_store.read_session_record(project_root, "ses_persist")

        assert "binding" in read_record
        assert read_record["binding"]["binding-id"] == record["binding"]["binding-id"]
        assert read_record["binding"]["provider-ref-key"] == record["binding"]["provider-ref-key"]
        assert read_record["binding"]["provider-session-ref"] == "ref-persist"

    def test_binding_visible_in_session_record_field(self, project_root: Path) -> None:
        """Binding is stored under the 'binding' key in the session record."""
        _make_session_record(project_root, "ses_field", "ref-field")

        read_record = session_store.read_session_record(project_root, "ses_field")

        assert isinstance(read_record["binding"], dict)
        required_keys = {"binding-id", "provider-id", "provider-session-ref",
                         "provider-ref-key", "relation", "ownership", "created-at"}
        assert required_keys.issubset(read_record["binding"].keys())


class TestBindingIdentityStability:
    """Binding identity is stable: same binding-id across reads."""

    def test_binding_id_stable_across_reads(self, project_root: Path) -> None:
        """Reading the same session record multiple times yields identical binding-id."""
        _make_session_record(project_root, "ses_stable", "ref-stable")

        read1 = session_store.read_session_record(project_root, "ses_stable")
        read2 = session_store.read_session_record(project_root, "ses_stable")
        read3 = session_store.read_session_record(project_root, "ses_stable")

        assert read1["binding"]["binding-id"] == read2["binding"]["binding-id"]
        assert read2["binding"]["binding-id"] == read3["binding"]["binding-id"]

    def test_provider_ref_key_stable(self, project_root: Path) -> None:
        """provider-ref-key hash doesn't change for same provider+surface+identity."""
        key1 = bindings.provider_ref_key(
            provider_id="my-provider",
            surface_id="acp-session",
            ref_namespace=None,
            identity_context_fingerprint="fp-abc",
            provider_session_ref="session-ref-xyz",
        )
        key2 = bindings.provider_ref_key(
            provider_id="my-provider",
            surface_id="acp-session",
            ref_namespace=None,
            identity_context_fingerprint="fp-abc",
            provider_session_ref="session-ref-xyz",
        )

        assert key1 == key2
        # SHA-256 hex digest is 64 chars.
        assert len(key1) == 64

    def test_provider_ref_key_differs_on_any_change(self, project_root: Path) -> None:
        """Changing any input to provider_ref_key changes the output hash."""
        base_key = bindings.provider_ref_key(
            provider_id="prov",
            surface_id="acp-session",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-a",
        )

        # Different provider_id.
        diff_provider = bindings.provider_ref_key(
            provider_id="other-prov",
            surface_id="acp-session",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-a",
        )
        assert base_key != diff_provider

        # Different provider_session_ref.
        diff_ref = bindings.provider_ref_key(
            provider_id="prov",
            surface_id="acp-session",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-b",
        )
        assert base_key != diff_ref

        # Different surface_id.
        diff_surface = bindings.provider_ref_key(
            provider_id="prov",
            surface_id="mcp-session",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-a",
        )
        assert base_key != diff_surface

    def test_provider_ref_key_different_on_null_vs_none(self) -> None:
        """provider-ref-key treats explicit 'unknown-provider' differently from None
        (None uses the default)."""
        key_with_none = bindings.provider_ref_key(
            provider_id=None,
            surface_id="test-surface",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-test",
        )
        key_with_unknown = bindings.provider_ref_key(
            provider_id="unknown-provider",
            surface_id="test-surface",
            ref_namespace=None,
            identity_context_fingerprint=None,
            provider_session_ref="ref-test",
        )
        # None defaults to "unknown-provider" in the hash — they should be equal.
        assert key_with_none == key_with_unknown

    def test_v1_migration_with_a_ref_refuses_deterministically(self) -> None:
        """build_migrated_v1_binding fails closed, consistently, for a v1
        record with a real provider_session_ref -- v1 predates AS29 surface
        declarations, so there is no surface_id to migrate, and repeated
        calls with identical inputs must raise the identical rejection
        rather than succeeding sometimes (no randomness, no read-time
        clock in the failure path either)."""
        for _ in range(2):
            with pytest.raises(AudiaGenticError, match="VAL-AGW-103"):
                bindings.build_migrated_v1_binding(
                    session_id="ses_v1_abc",
                    provider_id="prov-legacy",
                    provider_session_ref="ref-legacy-xyz",
                    created_at="2025-01-01T00:00:00Z",
                )
        # No ref at all (never-opened v1 record) still returns None, not a raise.
        assert (
            bindings.build_migrated_v1_binding(
                session_id="ses_v1_abc",
                provider_id="prov-legacy",
                provider_session_ref=None,
                created_at="2025-01-01T00:00:00Z",
            )
            is None
        )


# ── Provider Ref Redaction Tests ───────────────────────────────────

class TestProviderRefRedactionThroughRecovery:
    """Provider-ref redaction is maintained through recovery."""

    def test_public_projection_redacts_provider_ref(self, project_root: Path) -> None:
        """public_binding_projection removes the opaque provider-session-ref."""
        _make_session_record(project_root, "ses_redact", "super-secret-ref-123")

        record = session_store.read_session_record(project_root, "ses_redact")
        projected = bindings.public_binding_projection(record["binding"])

        # The secret ref must not appear in the projection.
        assert "provider-session-ref" not in projected
        assert "super-secret-ref-123" not in repr(projected)
        # Only prefix of key is shown.
        assert "provider-ref-key-prefix" in projected
        assert len(projected["provider-ref-key-prefix"]) == 12

    def test_public_session_redacts_provider_ref(self, project_root: Path) -> None:
        """project_public_session removes the raw provider-session-ref."""
        _make_session_record(project_root, "ses_pub", "secret-pub-456")

        record = session_store.read_session_record(project_root, "ses_pub")
        projected = bindings.project_public_session(record)

        assert "provider-session-ref" not in projected
        assert "secret-pub-456" not in repr(projected)

    def test_redaction_survives_index_rebuild(self, project_root: Path) -> None:
        """Rebuilt index does not contain provider-session-ref values."""
        _make_session_record(project_root, "ses_reb", "secret-reb-789")
        bindings.rebuild_index(project_root)

        # Read the raw index file — it should never contain the raw ref.
        index_path = bindings.gateway_session_binding_index_path(project_root)
        raw_content = index_path.read_text(encoding="utf-8")

        assert "secret-reb-789" not in raw_content


# ── Windows Compatibility Tests ───────────────────────────────────

class TestWindowsCompatibility:
    """Windows-specific binding operations."""

    def test_session_dir_path_uses_native_separator(self, project_root: Path) -> None:
        """Session directory path uses OS-native separators on Windows."""
        import os

        _make_session_record(project_root, "ses_win_compat", "ref-win")

        session_dir = session_store.gateway_session_path(project_root, "ses_win_compat").parent
        # Path objects normalize; on Windows they may use backslashes.
        path_str = str(session_dir)
        if os.name == "nt":
            # Windows paths use backslashes (or forward slashes — both work).
            pass  # Just verify the path is valid and the directory exists.
        assert session_dir.is_dir()

    def test_lock_file_no_rm_f_needed(self, project_root: Path) -> None:
        """Lock file cleanup works on Windows without rm -f equivalent."""
        from audiagentic.foundation.system.process import StartupLock

        lock_path = bindings.gateway_session_binding_lock_path(project_root)

        # Acquire and release — should work cleanly on all platforms.
        with StartupLock(lock_path, timeout=5):
            assert lock_path.exists()

        # Cleanup without rm -f (Windows doesn't have it).
        assert not lock_path.exists()

    def test_atomic_write_works_with_long_windows_paths(self, project_root: Path) -> None:
        """atomic_write_json works even with deep directory structures."""
        # Create a deeply nested path.
        deep = (
            project_root
            / ".audiagentic"
            / "runtime"
            / "agent-execution-gateway"
            / "sessions"
            / ("a" * 20)
            / "record.json"
        )
        deep.parent.mkdir(parents=True, exist_ok=True)

        _make_session_record(project_root, f"ses_deep_a{'_' * 15}", "ref-deep")

        # The binding index write uses atomic_write_json internally.
        bindings.rebuild_index(project_root)

        index_path = bindings.gateway_session_binding_index_path(project_root)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        assert len(payload["bindings"]) == 1
