"""Unit tests for foundation.i18n — I18n registry class and error helper.

Covers all lookup paths: hit in locale, fallback to default, fallback to key,
interpolation, plural forms, unknown locale, and the _t_err error helper.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# Reset I18n singleton between tests so each test gets a clean state.
@pytest.fixture(autouse=True)
def _reset_i18n():
    from audiagentic.foundation import i18n as i18n_mod

    original = i18n_mod._i18n_instance
    i18n_mod._i18n_instance = None
    yield
    i18n_mod._i18n_instance = original


@pytest.fixture
def locale_root(tmp_path: Path) -> Path:
    """Create a locale directory with test data for multiple components and locales."""
    # Planning component — English
    planning_en = tmp_path / "locales" / "planning" / "en.yaml"
    planning_en.parent.mkdir(parents=True)
    planning_en.write_text(
        "item_plan_required: \"The plan field is required.\"\n"
        "item_not_found: \"Plan item not found: {item_id!r}\"\n"
        "files:\n"
        "  one: \"{count} file found\"\n"
        "  other: \"{count} files found\"\n"
        "errors:\n"
        "  VAL-PLN-003: \"The 'plan' field is required.\"\n"
    )

    # Planning component — German (partial, to test fallback)
    planning_de = tmp_path / "locales" / "planning" / "de.yaml"
    planning_de.write_text(
        "item_plan_required: \"Das Planfeld ist erforderlich.\"\n"
    )

    # Foundation component — English
    foundation_en = tmp_path / "locales" / "foundation" / "en.yaml"
    foundation_en.parent.mkdir(parents=True)
    foundation_en.write_text(
        "gateway: \"Gateway unavailable\"\n"
    )

    return tmp_path


# ── Basic lookup ────────────────────────────────────────────────────

class TestBasicLookup:
    def test_uninitialized_returns_key(self):
        from audiagentic.foundation.i18n import I18n

        # Before initialization, returns the key itself
        assert I18n.t("planning.item_plan_required") == "planning.item_plan_required"

    def test_basic_hit_in_default_locale(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        assert I18n.t("planning.item_plan_required") == "The plan field is required."

    def test_nested_key_lookup(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        assert I18n.t("planning.files.one") == "{count} file found"

    def test_cross_component_lookup(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        assert I18n.t("foundation.gateway") == "Gateway unavailable"


# ── Fallback chain ─────────────────────────────────────────────────

class TestFallbackChain:
    def test_fallback_to_default_locale(self, locale_root: Path):
        """When a key exists in default locale but not requested locale."""
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        # "item_not_found" is only in en.yaml, not de.yaml
        I18n.set_locale("de")
        assert I18n.t("planning.item_not_found", item_id="CC01") == "Plan item not found: 'CC01'"

    def test_fallback_to_key_when_missing(self, locale_root: Path):
        """When a key doesn't exist in any locale."""
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        assert I18n.t("planning.nonexistent_key") == "planning.nonexistent_key"

    def test_per_call_locale_override(self, locale_root: Path):
        """Per-call locale takes precedence over default."""
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        I18n.set_locale("de")
        # Override back to English for this call
        assert I18n.t("planning.item_plan_required", locale="en") == "The plan field is required."

    def test_unknown_locale_falls_back_to_default(self, locale_root: Path):
        """Unknown locale doesn't crash; falls back to default."""
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        result = I18n.t("planning.item_plan_required", locale="xx")
        assert result == "The plan field is required."


# ── Interpolation ──────────────────────────────────────────────────

class TestInterpolation:
    def test_basic_interpolation(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        result = I18n.t("planning.item_not_found", item_id="CC01")
        assert result == "Plan item not found: 'CC01'"

    def test_interpolation_uses_rrepr(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        result = I18n.t("planning.item_not_found", item_id=42)
        assert result == "Plan item not found: 42"

    def test_extra_context_keys_are_safe(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        # Template only uses {item_id}, extra keys don't cause errors
        result = I18n.t("planning.item_not_found", item_id="CC01", unused_var=99)
        assert result == "Plan item not found: 'CC01'"

    def test_missing_context_key_keeps_placeholder(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        # Template uses {item_id} but we don't provide it — safe fallback
        result = I18n.t("planning.item_not_found")
        assert "item_id" in result  # placeholder remains


# ── Locale management ──────────────────────────────────────────────

class TestLocaleManagement:
    def test_default_locale_is_en(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        assert I18n.get_locale() == "en"

    def test_set_locale_persists(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        I18n.set_locale("de")
        assert I18n.get_locale() == "de"
        assert I18n.t("planning.item_plan_required") == "Das Planfeld ist erforderlich."

    def test_set_locale_fallback_works(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        I18n.set_locale("de")
        # "item_not_found" only in en — should fall back
        result = I18n.t("planning.item_not_found", item_id="X")
        assert result == "Plan item not found: 'X'"


# ── Pluralization ──────────────────────────────────────────────────

class TestPluralization:
    def test_singular_form(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        result = I18n.t_plural("planning.files.one", "planning.files.other", 1)
        assert result == "1 file found"

    def test_plural_form(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        result = I18n.t_plural("planning.files.one", "planning.files.other", 3)
        assert result == "3 files found"

    def test_zero_uses_other(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        result = I18n.t_plural("planning.files.one", "planning.files.other", 0)
        assert result == "0 files found"

    def test_per_call_locale_override(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        # German translation would use different plural rules if we had them
        result = I18n.t_plural(
            "planning.files.one", "planning.files.other", 3, locale="en"
        )
        assert result == "3 files found"

    def test_additional_context_injected(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        # Extra context is passed through along with count
        result = I18n.t_plural(
            "planning.files.one",
            "planning.files.other",
            5,
            extra="bonus",
        )
        assert "5" in result

    def test_fallback_english_when_babel_unavailable(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        initialize([locale_root])
        # Even with an unknown locale, should use English-style singular/plural
        result = I18n.t_plural(
            "planning.files.one", "planning.files.other", 3, locale="zz"
        )
        assert result == "3 files found"


# ── Error helper ───────────────────────────────────────────────────

class TestErrorHelper:
    def test_resolves_planning_error(self, locale_root: Path):
        from audiagentic.foundation.i18n import _t_err, initialize

        initialize([locale_root])
        result = _t_err("VAL-PLN-003")
        assert result == "The 'plan' field is required."

    def test_falls_back_to_code_when_not_found(self, locale_root: Path):
        from audiagentic.foundation.i18n import _t_err, initialize

        initialize([locale_root])
        # VAL-PLN-999 doesn't exist in any locale
        result = _t_err("VAL-PLN-999")
        assert result == "planning.errors.VAL-PLN-999"

    def test_unmapped_prefix_falls_back_to_code(self):
        from audiagentic.foundation.i18n import _t_err

        # Unknown prefix falls back to code
        result = _t_err("XXX-YYY-001")
        assert result == "XXX-YYY-001"

    def test_interpolation_in_error_helper(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, _t_err, initialize

        initialize([locale_root])
        # Override the message to include interpolation placeholder
        I18n.set_locale("en")
        result = _t_err("VAL-PLN-003", extra="detail")
        assert "'plan' field is required" in result


# ── Module-level convenience ───────────────────────────────────────

class TestModuleConvenience:
    def test_initialize_and_get_instance(self, locale_root: Path):
        from audiagentic.foundation.i18n import get_instance, initialize

        initialize([locale_root])
        inst = get_instance()
        assert inst.get_locale() == "en"
        result = inst.t("planning.item_plan_required")
        assert result == "The plan field is required."

    def test_deep_merge_layering(self, locale_root: Path):
        from audiagentic.foundation.i18n import I18n, initialize

        # Create a second config dir with overlapping data
        override_dir = locale_root.parent / "override"
        planning_dir = override_dir / "locales" / "planning"
        planning_dir.mkdir(parents=True)
        (planning_dir / "en.yaml").write_text(
            "files:\n"
            "  one: \"{count} item found\"\n"
        )

        # Initialize with both dirs — later dir should override
        initialize([locale_root, override_dir])
        assert I18n.t("planning.files.one") == "{count} item found"
        # Unchanged key from first dir still works
        assert I18n.t("planning.item_plan_required") == "The plan field is required."
