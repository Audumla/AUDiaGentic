"""Tests for generic configuration-completeness evaluation.

The derivation is component-agnostic: it operates purely on an OptionSchema map
plus an options mapping, and must hold no knowledge of any specific component.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.features.base import OptionSchema
from audiagentic.foundation.features.config_status import (
    evaluate_config,
    implementation_config_status,
)


class TestEvaluateConfig:
    def test_no_schema_is_configured(self) -> None:
        status = evaluate_config({}, {})
        assert status.configured is True
        assert status.missing_required == ()

    def test_only_optional_options_is_configured(self) -> None:
        schema = {"timeout": OptionSchema(option_type="integer", default=30)}
        status = evaluate_config(schema, {})
        assert status.configured is True
        assert status.effective_options == {"timeout": 30}

    def test_missing_required_option_is_not_configured(self) -> None:
        schema = {
            "base-url": OptionSchema(
                option_type="string", required=True, description="Server URL"
            ),
        }
        status = evaluate_config(schema, {})
        assert status.configured is False
        assert len(status.missing_required) == 1
        assert status.missing_required[0].key == "base-url"
        assert status.missing_required[0].description == "Server URL"

    def test_present_required_option_is_configured(self) -> None:
        schema = {"base-url": OptionSchema(option_type="string", required=True)}
        status = evaluate_config(schema, {"base-url": "https://x"})
        assert status.configured is True
        assert status.missing_required == ()

    def test_required_with_default_is_satisfied_by_default(self) -> None:
        schema = {"mode": OptionSchema(option_type="string", required=True, default="http")}
        status = evaluate_config(schema, {})
        assert status.configured is True

    def test_optional_present_does_not_satisfy_required_missing(self) -> None:
        schema = {
            "base-url": OptionSchema(option_type="string", required=True),
            "timeout": OptionSchema(option_type="integer", default=30),
        }
        # Setting only the optional must NOT flip configured to true.
        status = evaluate_config(schema, {"timeout": 15})
        assert status.configured is False
        assert [m.key for m in status.missing_required] == ["base-url"]

    def test_does_not_raise_on_unknown_options(self) -> None:
        # Status derivation is read-only; unknown keys are tolerated, not validated.
        status = evaluate_config({}, {"stray": "value"})
        assert status.configured is True
        assert status.effective_options == {"stray": "value"}


class TestOptionSchemaMetadata:
    def test_required_and_description_load_from_yaml_mapping(self) -> None:
        from audiagentic.foundation.features.options import option_schema_from_mapping

        schema = option_schema_from_mapping(
            {"type": "string", "required": True, "description": "Server URL"}
        )
        assert schema.required is True
        assert schema.description == "Server URL"

    def test_metadata_defaults_when_absent(self) -> None:
        from audiagentic.foundation.features.options import option_schema_from_mapping

        schema = option_schema_from_mapping({"type": "string"})
        assert schema.required is False
        assert schema.description == ""


class TestImplementationConfigStatus:
    def test_reflects_missing_required_from_registered_schema(self, tmp_path: Path) -> None:
        from audiagentic.foundation.components.loader import register_all_components

        register_all_components()
        # hindsight declares host required; fresh root has no options set.
        status = implementation_config_status(tmp_path, "memory", "hindsight")
        assert status.implementation_id == "hindsight"
        assert status.configured is False
        assert "host" in [m.key for m in status.missing_required]

    def test_configured_after_required_option_set(self, tmp_path: Path) -> None:
        from audiagentic.foundation.components.loader import register_all_components
        from audiagentic.foundation.features.base import ImplementationState
        from audiagentic.foundation.features.state import set_implementation_state

        register_all_components()
        set_implementation_state(
            tmp_path,
            "memory",
            "hindsight",
            ImplementationState(enabled=True, options={"host": "10.10.100.10"}),
        )
        status = implementation_config_status(tmp_path, "memory", "hindsight")
        assert status.enabled is True
        assert status.configured is True
        assert status.missing_required == ()

    def test_unknown_implementation_has_empty_schema_and_is_configured(self, tmp_path: Path) -> None:
        # No descriptor → empty schema → vacuously configured (nothing required).
        status = implementation_config_status(tmp_path, "memory", "does-not-exist")
        assert status.configured is True
        assert status.missing_required == ()
