import pytest

from audiagentic.components.providers.contracts.lifecycle_modes import (
    normalize_provider_cli_mode,
    provider_cli_mode_from_user_verb,
)


class TestProviderCliModeFromUserVerb:
    """Test the user-verb-to-internal-mode translator."""

    def test_install_maps_to_apply(self):
        assert provider_cli_mode_from_user_verb("install") == "apply"

    def test_uninstall_maps_to_prune(self):
        assert provider_cli_mode_from_user_verb("uninstall") == "prune"

    def test_repair_maps_to_apply(self):
        assert provider_cli_mode_from_user_verb("repair") == "apply"

    def test_case_insensitive(self):
        assert provider_cli_mode_from_user_verb("INSTALL") == "apply"
        assert provider_cli_mode_from_user_verb("Uninstall") == "prune"
        assert provider_cli_mode_from_user_verb("REPAIR") == "apply"

    def test_whitespace_stripped(self):
        assert provider_cli_mode_from_user_verb("  install  ") == "apply"

    def test_unknown_verb_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported provider lifecycle verb"):
            provider_cli_mode_from_user_verb("delete")

    def test_error_message_includes_supported_verbs(self):
        with pytest.raises(ValueError) as exc_info:
            provider_cli_mode_from_user_verb("foo")
        msg = str(exc_info.value)
        assert "install" in msg
        assert "uninstall" in msg
        assert "repair" in msg


class TestNormalizeProviderCliMode:
    """Test the CLI lifecycle mode normalizer."""

    def test_all_valid_modes_pass(self):
        for mode in ("plan", "apply", "prune", "status"):
            assert normalize_provider_cli_mode(mode) == mode

    def test_case_insensitive(self):
        assert normalize_provider_cli_mode("APPLY") == "apply"
        assert normalize_provider_cli_mode("Plan") == "plan"

    def test_whitespace_stripped(self):
        assert normalize_provider_cli_mode("  prune  ") == "prune"

    def test_unknown_mode_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported provider CLI lifecycle mode"):
            normalize_provider_cli_mode("rollback")

    def test_error_message_includes_supported_modes(self):
        with pytest.raises(ValueError) as exc_info:
            normalize_provider_cli_mode("foo")
        msg = str(exc_info.value)
        assert "plan" in msg
        assert "apply" in msg
        assert "prune" in msg
        assert "status" in msg
