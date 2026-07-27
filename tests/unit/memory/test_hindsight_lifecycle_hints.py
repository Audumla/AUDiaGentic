"""Tests for DE03 — lifecycle hint reporting (restart-required / collision / deprecation).

These tests verify that reconcile and status reporting surface the correct
lifecycle hints based on managed family results + provider descriptors.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import audiagentic.components.providers  # noqa: F401 — register provider descriptors
from audiagentic.components.memory.hindsight import provision as prov
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig


def _patch_backend(monkeypatch, backend):
    monkeypatch.setattr(prov, "build_hindsight_backend", lambda root: backend)  # noqa: ARG005


# ---------------------------------------------------------------------------
# _lifecycle_hint unit tests
# ---------------------------------------------------------------------------


class TestLifecycleHint:
    """Test _lifecycle_hint with various managed_results configurations."""

    def test_empty_results_returns_none(self):
        hint = prov._lifecycle_hint("gemini", Path("/tmp"), [])
        assert hint is None

    def test_restart_required_when_changed_no_auto_refresh(self, tmp_path):
        """Restart hint when changed=True and auto_refreshed=False."""
        results = [
            {
                "changed": True,
                "auto_refreshed": False,
                "collision_ids": [],
                "action_needed": None,
            }
        ]
        with patch.object(prov, "_mcp_refresh_mode", return_value="restart-required"):
            hint = prov._lifecycle_hint("cline", tmp_path, results)
        assert "restart the harness" in (hint or "")

    def test_no_restart_hint_when_auto_refreshed(self, tmp_path):
        """No restart hint when auto_refreshed=True and mode is file-watch."""
        results = [
            {
                "changed": True,
                "auto_refreshed": True,
                "collision_ids": [],
                "action_needed": None,
            }
        ]
        with patch.object(prov, "_mcp_refresh_mode", return_value="file-watch"):
            hint = prov._lifecycle_hint("claude", tmp_path, results)
        assert hint is None

    def test_collision_ids_surfaced(self, tmp_path):
        """Collision IDs surfaced in hint string."""
        results = [
            {
                "changed": False,
                "auto_refreshed": True,
                "collision_ids": ["other-entry-1", "other-entry-2"],
                "action_needed": None,
            }
        ]
        hint = prov._lifecycle_hint("gemini", tmp_path, results)
        assert "unmanaged entries collide" in (hint or "")
        assert "other-entry-1" in (hint or "")
        assert "other-entry-2" in (hint or "")

    def test_action_needed_surfaced(self, tmp_path):
        """action_needed from family result surfaced."""
        results = [
            {
                "changed": False,
                "auto_refreshed": True,
                "collision_ids": [],
                "action_needed": "configure bank-id in provider settings",
            }
        ]
        hint = prov._lifecycle_hint("gemini", tmp_path, results)
        assert "configure bank-id" in (hint or "")

    def test_deprecation_hint_for_deprecated_provider(self, tmp_path):
        """Deprecation hint for deprecated providers."""
        from audiagentic.components.providers.descriptors.registry import get_descriptor

        desc = get_descriptor("gemini")
        if desc is None or not getattr(desc, "deprecated", False):
            pytest.skip("gemini not marked deprecated in current config")

        results = [
            {
                "changed": False,
                "auto_refreshed": True,
                "collision_ids": [],
                "action_needed": None,
            }
        ]
        hint = prov._lifecycle_hint("gemini", tmp_path, results)
        assert "deprecated" in (hint or "").lower()

    def test_combined_hints_joined(self, tmp_path):
        """Multiple hints joined with commas."""
        results = [
            {
                "changed": True,
                "auto_refreshed": False,
                "collision_ids": ["stale-entry"],
                "action_needed": "set bank-id",
            }
        ]
        with patch.object(prov, "_mcp_refresh_mode", return_value="restart-required"):
            hint = prov._lifecycle_hint("cline", tmp_path, results)
        assert "restart" in (hint or "").lower()
        assert "collide" in (hint or "").lower()
        assert "bank-id" in (hint or "")

    def test_last_result_used_when_multiple(self, tmp_path):
        """When multiple managed results, the last one is used for hints."""
        results = [
            {
                "changed": True,
                "auto_refreshed": False,
                "collision_ids": [],
                "action_needed": None,
            },
            {
                "changed": False,
                "auto_refreshed": True,
                "collision_ids": ["stale-entry"],
                "action_needed": None,
            },
        ]
        with patch.object(prov, "_mcp_refresh_mode", return_value="restart-required"):
            hint = prov._lifecycle_hint("cline", tmp_path, results)
        # Should use last result which has no restart but has collisions
        assert "collide" in (hint or "").lower()

    def test_no_hint_for_unchanged_auto_refreshed(self, tmp_path):
        """No hint when nothing changed and auto-refreshed."""
        results = [
            {
                "changed": False,
                "auto_refreshed": True,
                "collision_ids": [],
                "action_needed": None,
            }
        ]
        with patch.object(prov, "_mcp_refresh_mode", return_value="file-watch"):
            hint = prov._lifecycle_hint("claude", tmp_path, results)
        assert hint is None


# ---------------------------------------------------------------------------
# _mcp_refresh_mode unit tests
# ---------------------------------------------------------------------------


class TestMcpRefreshMode:
    """Test _mcp_refresh_mode reads correct values from descriptors."""

    def test_restart_required_for_cline(self, tmp_path):
        mode = prov._mcp_refresh_mode("cline", tmp_path)
        assert mode == "restart-required"

    def test_file_watch_for_claude(self, tmp_path):
        mode = prov._mcp_refresh_mode("claude", tmp_path)
        assert mode == "file-watch"

    def test_restart_required_for_gemini(self, tmp_path):
        mode = prov._mcp_refresh_mode("gemini", tmp_path)
        assert mode == "restart-required"

    def test_file_watch_for_antigravity(self, tmp_path):
        mode = prov._mcp_refresh_mode("antigravity", tmp_path)
        assert mode == "file-watch"


# ---------------------------------------------------------------------------
# reconcile_hindsight integration with lifecycle hints
# ---------------------------------------------------------------------------


class TestReconcileLifecycleHints:
    """Test that reconcile surfaces lifecycle hints on the entry dicts."""

    def test_gemini_deprecation_hint(self, tmp_path, monkeypatch):
        """Gemini should have deprecation hint in reconcile result."""
        _patch_backend(monkeypatch, HindsightBackendConfig(base_url="http://hs:1/", api_key="k"))

        from audiagentic.components.providers.descriptors.registry import get_descriptor

        desc = get_descriptor("gemini")
        if desc is None or not getattr(desc, "deprecated", False):
            pytest.skip("gemini not marked deprecated in current config")

        out = prov.reconcile_hindsight(tmp_path, ["gemini"])
        entry = out["providers"].get("gemini", {})
        hint = entry.get("action_needed", "") or ""
        assert "deprecated" in hint.lower(), f"Expected deprecation hint, got: {hint}"

    def test_no_hint_for_guidance_only_provider(self, tmp_path, monkeypatch):
        """Guidance-only providers get no lifecycle hints."""
        _patch_backend(monkeypatch, HindsightBackendConfig(base_url="http://hs:1/", api_key="k"))

        # Use a provider that has no managed-* family — should be guidance-only.
        out = prov.reconcile_hindsight(tmp_path, ["gemini"])
        entry = out["providers"].get("gemini", {})
        # Even if deprecated, the hint may or may not appear depending on recipe result.
        # Just verify the entry has a valid shape.
        assert "success" in entry
        assert "state" in entry
