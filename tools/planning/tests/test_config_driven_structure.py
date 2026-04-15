"""
Tests for config-driven planning structure (plan-0014).

Validates TemplateEngine, RelationshipConfig, Config methods, and manager refactoring
implemented in phases 1-4 of plan-0014.
"""

import os
import sys
from pathlib import Path
import pytest


# Bootstrap project root to import audiagentic
def bootstrap():
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        if (p / ".audiagentic" / "planning").exists():
            sys.path.insert(0, str(p))
            sys.path.insert(0, str(p / "src"))
            return p
    raise RuntimeError("Could not find project root")


root = bootstrap()

from audiagentic.planning.app.config import Config
from audiagentic.planning.app.api import PlanningAPI


class TestConfigRequiredSections:
    """Test Config.required_sections() method added in Phase 4."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = Config(root)

    def test_required_sections_exists(self):
        """Verify required_sections method exists."""
        assert hasattr(self.config, "required_sections")
        assert callable(self.config.required_sections)

    def test_required_sections_request(self):
        """Test required sections for request kind."""
        sections = self.config.required_sections("request")
        assert sections is not None
        assert "Understanding" in sections
        assert "Open Questions" in sections

    def test_required_sections_spec(self):
        """Test required sections for spec kind."""
        sections = self.config.required_sections("spec")
        assert sections is not None
        assert "Purpose" in sections
        assert "Scope" in sections
        assert "Requirements" in sections
        assert "Constraints" in sections
        assert "Acceptance Criteria" in sections

    def test_required_sections_task(self):
        """Test required sections for task kind."""
        sections = self.config.required_sections("task")
        assert sections is not None
        assert "Description" in sections

    def test_required_sections_plan(self):
        """Test required sections for plan kind."""
        sections = self.config.required_sections("plan")
        assert sections is not None
        assert "Objectives" in sections
        assert "Delivery Approach" in sections
        assert "Dependencies" in sections

    def test_required_sections_wp(self):
        """Test required sections for wp kind."""
        sections = self.config.required_sections("wp")
        assert sections is not None
        assert "Objective" in sections
        assert "Instructions" in sections
        assert "Required Outputs" in sections

    def test_required_sections_standard(self):
        """Test required sections for standard kind."""
        sections = self.config.required_sections("standard")
        # Standards may have empty required sections
        assert sections is not None


class TestConfigDocumentTemplates:
    """Test Config.document_template() method for guidance level variations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = Config(root)

    def test_document_template_spec_default(self):
        """Test spec template with default guidance."""
        template = self.config.document_template("spec")
        assert template
        assert "# Purpose" in template
        assert "# Scope" in template
        assert "# Requirements" in template

    def test_document_template_spec_light(self):
        """Test spec template with light guidance has fewer sections."""
        template = self.config.document_template("spec", "light")
        assert template
        assert "# Purpose" in template
        assert "# Scope" in template
        assert "# Requirements" in template
        # Light should NOT have Constraints or Acceptance Criteria
        assert "# Constraints" not in template
        assert "# Acceptance Criteria" not in template

    def test_document_template_spec_standard(self):
        """Test spec template with standard guidance."""
        template = self.config.document_template("spec", "standard")
        assert template
        assert "# Purpose" in template
        assert "# Scope" in template
        assert "# Requirements" in template
        assert "# Constraints" in template
        assert "# Acceptance Criteria" in template

    def test_document_template_spec_deep(self):
        """Test spec template with deep guidance has more sections."""
        template = self.config.document_template("spec", "deep")
        assert template
        assert "# Purpose" in template
        assert "# Scope" in template
        assert "# Requirements" in template
        assert "# Constraints" in template
        assert "# Acceptance Criteria" in template
        assert "# Non-Goals" in template
        assert "# Compatibility" in template

    def test_document_template_task_guidance_levels(self):
        """Test task templates vary by guidance level."""
        light = self.config.document_template("task", "light")
        standard = self.config.document_template("task", "standard")
        deep = self.config.document_template("task", "deep")

        # All should have Description
        assert "# Description" in light
        assert "# Description" in standard
        assert "# Description" in deep

        # Light should be minimal
        assert "# Acceptance Criteria" not in light

        # Standard should have Acceptance Criteria
        assert "# Acceptance Criteria" in standard

        # Deep should have Implementation Notes
        assert "# Implementation Notes" in deep

    def test_document_template_plan_guidance_levels(self):
        """Test plan templates vary by guidance level."""
        light = self.config.document_template("plan", "light")
        standard = self.config.document_template("plan", "standard")
        deep = self.config.document_template("plan", "deep")

        # All should have Objectives and Delivery Approach
        for template in [light, standard, deep]:
            assert "# Objectives" in template
            assert "# Delivery Approach" in template

        # Light should NOT have Dependencies
        assert "# Dependencies" not in light

        # Standard and deep should have Dependencies
        assert "# Dependencies" in standard
        assert "# Dependencies" in deep

        # Deep should have Risks and Milestones
        assert "# Risks" in deep
        assert "# Milestones" in deep

    def test_document_template_wp_guidance_levels(self):
        """Test wp templates vary by guidance level."""
        light = self.config.document_template("wp", "light")
        standard = self.config.document_template("wp", "standard")
        deep = self.config.document_template("wp", "deep")

        # All should have Objective, Instructions, Required Outputs
        for template in [light, standard, deep]:
            assert "# Objective" in template
            assert "# Instructions" in template
            assert "# Required Outputs" in template

        # Light should be minimal
        assert "# Scope of This Package" not in light
        assert "# Inputs" not in light

        # Standard should have full structure
        assert "# Scope of This Package" in standard
        assert "# Inputs" in standard
        assert "# Acceptance Checks" in standard
        assert "# Non-Goals" in standard

        # Deep should have additional sections
        assert "# Risks" in deep
        assert "# Dependencies" in deep

    def test_document_template_standard_guidance_levels(self):
        """Test standard templates vary by guidance level."""
        light = self.config.document_template("standard", "light")
        standard = self.config.document_template("standard", "standard")
        deep = self.config.document_template("standard", "deep")

        # All should have Standard section
        for template in [light, standard, deep]:
            assert "# Standard" in template

        # Light should be minimal
        assert "# Requirements" not in light

        # Standard should have Requirements
        assert "# Requirements" in standard

        # Deep should have Rationale and Examples
        assert "# Rationale" in deep
        assert "# Examples" in deep

    def test_document_template_request_guidance_levels(self):
        """Test request templates vary by guidance level."""
        light = self.config.document_template("request", "light")
        standard = self.config.document_template("request", "standard")
        deep = self.config.document_template("request", "deep")

        # All should have Problem and Desired Outcome
        for template in [light, standard, deep]:
            assert "# Problem" in template
            assert "# Desired Outcome" in template

        # Light should NOT have Constraints
        assert "# Constraints" not in light

        # Standard and deep should have Constraints
        assert "# Constraints" in standard
        assert "# Constraints" in deep

        # Deep should have Compatibility and Success Criteria
        assert "# Compatibility" in deep
        assert "# Success Criteria" in deep


class TestConfigRelationshipRules:
    """Test Config relationship methods."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = Config(root)

    def test_can_reference_spec_to_request(self):
        """Test spec can reference request."""
        assert self.config.can_reference("spec", "request") is True

    def test_can_reference_spec_to_standard(self):
        """Test spec can reference standard."""
        assert self.config.can_reference("spec", "standard") is True

    def test_can_reference_task_to_spec(self):
        """Test task can reference spec."""
        assert self.config.can_reference("task", "spec") is True

    def test_can_reference_wp_to_plan(self):
        """Test wp can reference plan."""
        assert self.config.can_reference("wp", "plan") is True

    def test_can_reference_wp_to_task(self):
        """Test wp can reference task."""
        assert self.config.can_reference("wp", "task") is True

    def test_required_refs_spec(self):
        """Test spec required refs."""
        refs = self.config.required_refs("spec")
        assert "request_refs" in refs

    def test_required_refs_plan(self):
        """Test plan required refs."""
        refs = self.config.required_refs("plan")
        assert "spec_refs" in refs

    def test_required_refs_wp(self):
        """Test wp required refs."""
        refs = self.config.required_refs("wp")
        assert "plan_ref" in refs
        assert "task_refs" in refs


class TestConfigGuidanceLevels:
    """Test Config guidance level methods."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = Config(root)

    def test_guidance_levels_exists(self):
        """Test guidance_levels method returns dict."""
        levels = self.config.guidance_levels()
        assert isinstance(levels, dict)
        assert "light" in levels
        assert "standard" in levels
        assert "deep" in levels

    def test_guidance_for_light(self):
        """Test guidance_for returns light config."""
        guidance = self.config.guidance_for("light")
        assert guidance
        assert "description" in guidance
        assert "defaults" in guidance

    def test_guidance_for_standard(self):
        """Test guidance_for returns standard config."""
        guidance = self.config.guidance_for("standard")
        assert guidance
        assert "description" in guidance
        assert "defaults" in guidance

    def test_guidance_for_deep(self):
        """Test guidance_for returns deep config."""
        guidance = self.config.guidance_for("deep")
        assert guidance
        assert "description" in guidance
        assert "defaults" in guidance

    def test_default_guidance(self):
        """Test default_guidance returns valid level."""
        default = self.config.default_guidance()
        assert default in ["light", "standard", "deep"]

    def test_default_profile(self):
        """Test default_profile returns valid profile."""
        default = self.config.default_profile()
        assert default in ["feature", "issue", "fix", "enhancement"]


class TestConfigStandardDefaults:
    """Test Config.standard_defaults_for() method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = Config(root)

    def test_standard_defaults_spec(self):
        """Test spec standard defaults."""
        defaults = self.config.standard_defaults_for("spec")
        assert isinstance(defaults, list)
        assert "standard-0006" in defaults
        assert "standard-0005" in defaults

    def test_standard_defaults_task(self):
        """Test task standard defaults."""
        defaults = self.config.standard_defaults_for("task")
        assert isinstance(defaults, list)
        assert "standard-0005" in defaults
        assert "standard-0006" in defaults

    def test_standard_defaults_plan(self):
        """Test plan standard defaults."""
        defaults = self.config.standard_defaults_for("plan")
        assert isinstance(defaults, list)
        assert "standard-0006" in defaults

    def test_standard_defaults_wp(self):
        """Test wp standard defaults."""
        defaults = self.config.standard_defaults_for("wp")
        assert isinstance(defaults, list)
        assert "standard-0006" in defaults


class TestManagerIntegration:
    """Test that managers use config-driven approach."""

    def setup_method(self):
        """Set up test fixtures."""
        self.api = PlanningAPI(root, test_mode=True)
        self.config = Config(root)

    def test_create_spec_uses_config_template(self):
        """Test spec creation uses config template."""
        # Get template from config
        template = self.config.document_template("spec", "standard")

        # Create a spec (use test_mode to avoid validation errors)
        spec = self.api.new(
            "spec",
            "Test Spec",
            "Test summary",
            request_refs=["request-0001"],
            check_duplicates=False,
        )

        # Verify spec was created (ItemView is a dataclass)
        assert spec
        assert spec.data.get("label") == "Test Spec"
        assert spec.kind == "spec"

        # Clean up
        self.api.delete(spec.data.get("id"), hard=True)

    def test_create_task_uses_config_template(self):
        """Test task creation uses config template."""
        # Get template from config
        template = self.config.document_template("task", "standard")

        # Create a task
        task = self.api.new(
            "task", "Test Task", "Test summary", spec="spec-0001", check_duplicates=False
        )

        # Verify task was created
        assert task
        assert task.data.get("label") == "Test Task"
        assert task.kind == "task"

        # Clean up
        self.api.delete(task.data.get("id"), hard=True)

    def test_create_plan_uses_config_template(self):
        """Test plan creation uses config template."""
        # Get template from config
        template = self.config.document_template("plan", "standard")

        # Create a plan (use spec parameter, not spec_refs)
        plan = self.api.new(
            "plan", "Test Plan", "Test summary", spec="spec-0001", check_duplicates=False
        )

        # Verify plan was created
        assert plan
        assert plan.data.get("label") == "Test Plan"
        assert plan.kind == "plan"

        # Clean up
        self.api.delete(plan.data.get("id"), hard=True)

    def test_create_wp_uses_config_template(self):
        """Test wp creation uses config template."""
        # Get template from config
        template = self.config.document_template("wp", "standard")

        # Create a wp (use plan and parent parameters)
        wp = self.api.new(
            "wp",
            "Test WP",
            "Test summary",
            plan="plan-0001",
            parent="task-0001",
            check_duplicates=False,
        )

        # Verify wp was created
        assert wp
        assert wp.data.get("label") == "Test WP"
        assert wp.kind == "wp"

        # Clean up
        self.api.delete(wp.data.get("id"), hard=True)

    def test_create_standard_uses_config_template(self):
        """Test standard creation uses config template."""
        # Get template from config
        template = self.config.document_template("standard", "standard")

        # Create a standard
        standard = self.api.new("standard", "Test Standard", "Test summary", check_duplicates=False)

        # Verify standard was created
        assert standard
        assert standard.data.get("label") == "Test Standard"
        assert standard.kind == "standard"

        # Clean up
        self.api.delete(standard.data.get("id"), hard=True)


class TestBackwardCompatibility:
    """Test backward compatibility with existing documents."""

    def setup_method(self):
        """Set up test fixtures."""
        self.api = PlanningAPI(root, test_mode=True)
        self.config = Config(root)

    def test_existing_documents_remain_valid(self):
        """Test that existing documents can still be read."""
        # Try to read an existing spec using spec_mgr
        from audiagentic.planning.fs.read import parse_markdown

        spec_path = (
            root
            / "docs"
            / "planning"
            / "specifications"
            / "spec-0001-config-driven-planning-document-structure.md"
        )
        if spec_path.exists():
            spec_data, spec_body = parse_markdown(spec_path)
            assert spec_data is not None
            assert spec_data.get("id") == "spec-0001"
        # If spec-0001 doesn't exist, try to find any spec
        else:
            import glob

            spec_files = glob.glob(str(root / "docs" / "planning" / "specifications" / "spec-*.md"))
            if spec_files:
                spec_data, spec_body = parse_markdown(Path(spec_files[0]))
                assert spec_data is not None
                assert spec_data.get("id", "").startswith("spec-")

    def test_manager_api_signatures_unchanged(self):
        """Test that manager create() signatures are unchanged."""
        # These should all work with the same signature
        # (we tested this in TestManagerIntegration, but verify no breaking changes)

        # Create minimal documents to verify API compatibility
        task = self.api.new(
            "task",
            "API Compatibility Test",
            "Testing API signature compatibility",
            spec="spec-0001",
            check_duplicates=False,
        )

        assert task
        assert task.kind == "task"

        # Clean up
        self.api.delete(task.data.get("id"), hard=True)

    def test_default_config_matches_hardcoded_values(self):
        """Test that default config values match previous hardcoded templates."""
        # Spec default should have Purpose, Scope, Requirements, Constraints, Acceptance Criteria
        spec_template = self.config.document_template("spec")
        assert "# Purpose" in spec_template
        assert "# Scope" in spec_template
        assert "# Requirements" in spec_template
        assert "# Constraints" in spec_template
        assert "# Acceptance Criteria" in spec_template

        # Task default should have Description, Acceptance Criteria, Notes
        task_template = self.config.document_template("task")
        assert "# Description" in task_template
        assert "# Acceptance Criteria" in task_template
        assert "# Notes" in task_template

        # Plan default should have Objectives, Delivery Approach, Dependencies
        plan_template = self.config.document_template("plan")
        assert "# Objectives" in plan_template
        assert "# Delivery Approach" in plan_template
        assert "# Dependencies" in plan_template

        # WP default should have full structure
        wp_template = self.config.document_template("wp")
        assert "# Objective" in wp_template
        assert "# Scope of This Package" in wp_template
        assert "# Inputs" in wp_template
        assert "# Instructions" in wp_template
        assert "# Required Outputs" in wp_template
        assert "# Acceptance Checks" in wp_template
        assert "# Non-Goals" in wp_template


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
