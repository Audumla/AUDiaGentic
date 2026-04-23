from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.planning_testkit import seed_planning_config

from audiagentic.planning.app.config import Config


def _seed_base_config(tmp_path: Path, include_optional: bool) -> Path:
    seed_planning_config(
        tmp_path,
        include_optional=include_optional,
        include_profile_packs=include_optional,
        include_templates=True,
    )
    return tmp_path


def test_config_optional_files_may_be_absent(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=False)
    cfg = Config(root)
    assert cfg.documentation == {}
    assert "request_profiles" in cfg.request_profiles
    assert cfg.request_profiles["request_profiles"] != {}
    assert cfg.profile_packs == {}
    assert cfg.validate() == []


def test_config_loads_optional_files_when_present(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.documentation["planning"]["documentation"]["enabled"] is True
    assert "feature" in cfg.request_profiles["request_profiles"]
    assert "standard" in cfg.profile_packs
    assert cfg.profile_packs["standard"]["profile_pack"]["id"] == "standard"


def test_config_validates_optional_files_when_present(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.validate() == []


def test_guidance_levels_exist(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    levels = cfg.guidance_levels()
    assert "light" in levels
    assert "standard" in levels
    assert "deep" in levels


def test_guidance_level_semantics(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    for level in ["light", "standard", "deep"]:
        level_config = cfg.guidance_for(level)
        assert "description" in level_config
        assert "label" in level_config
        assert "defaults" in level_config
        assert "sections_by_kind" in level_config
        assert "spec" in level_config["sections_by_kind"]
        assert "task" in level_config["sections_by_kind"]
        assert "acceptance_criteria_depth" in level_config
        assert "semantics" in level_config
        semantics = level_config["semantics"]
        assert "target_implementor" in semantics
        assert "philosophy" in semantics
        assert "use_cases" in semantics
        assert "expectations" in semantics


def test_creation_profiles_generic_accessor_matches_legacy_alias(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.creation_profiles() == cfg.request_profiles["request_profiles"]
    assert cfg.creation_profile_for("feature") == cfg.profile_for("feature")


def test_default_guidance(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    default = cfg.default_guidance()
    assert default in ["light", "standard", "deep"]
    assert default == "standard"


def test_guidance_defaults_applied(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    for level in ["light", "standard", "deep"]:
        level_config = cfg.guidance_for(level)
        defaults = level_config["defaults"]
        assert "current_understanding" in defaults
        assert "open_questions" in defaults
        assert isinstance(defaults["open_questions"], list)
        assert len(defaults["open_questions"]) > 0


def test_guidance_sections_by_depth(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    light = cfg.guidance_for("light")
    standard = cfg.guidance_for("standard")
    deep = cfg.guidance_for("deep")
    light_required = len(light["sections_by_kind"]["spec"]["required"])
    standard_required = len(standard["sections_by_kind"]["spec"]["required"])
    deep_required = len(deep["sections_by_kind"]["spec"]["required"])
    assert light_required <= standard_required <= deep_required
    assert light["acceptance_criteria_depth"] == "basic"
    assert standard["acceptance_criteria_depth"] == "standard"
    assert deep["acceptance_criteria_depth"] == "rigorous"
    assert (
        cfg.guidance_required_sections("standard", "spec")
        == standard["sections_by_kind"]["spec"]["required"]
    )
    assert (
        cfg.guidance_required_sections("standard", "task")
        == standard["sections_by_kind"]["task"]["required"]
    )


def test_state_section_requirements_load(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.state_required_sections("task", "done") == ["Implementation Notes"]
    assert cfg.state_required_sections("task", "draft") == []


def test_required_sections_fall_back_to_template_headings(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.required_sections("spec") == [
        "Purpose",
        "Scope",
        "Requirements",
        "Constraints",
        "Acceptance Criteria",
    ]
    assert cfg.required_sections("plan") == [
        "Objectives",
        "Delivery Approach",
        "Dependencies",
    ]


def test_request_creation_sections_merge_template_profile_and_required(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.creation_sections("request", guidance="standard", profile="feature") == [
        "Problem",
        "Desired Outcome",
        "Constraints",
        "Open Questions",
    ]


def test_document_template_loads_from_markdown_template_files(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert "# Purpose" in cfg.document_template("spec")
    assert "# Non-Goals" in cfg.document_template("spec", "deep")
    assert "# Desired Outcome" in cfg.document_template("request")


def test_all_reference_fields_union_configured_kinds(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert set(cfg.all_reference_fields()) >= {
        "request_refs",
        "spec_ref",
        "spec_refs",
        "standard_refs",
        "task_refs",
        "plan_ref",
        "work_package_refs",
        "parent_task_ref",
    }


def test_reference_field_shape_reads_config_override(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.reference_field_shape("task_refs") == "rel_list"
    assert cfg.reference_field_shape("work_package_refs") == "rel_list"
    assert cfg.reference_field_shape("spec_refs") == "scalar_ref_list"


def test_state_cascades_are_loaded_from_config(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.state_cascades("request", "archived") == {"spec": "archived", "task": "archived"}
    assert cfg.state_cascades("request", "superseded") == {"spec": "superseded"}
    assert cfg.state_cascades("spec", "archived") == {"plan": "archived", "task": "archived"}


def test_lifecycle_state_sets_load_per_kind_and_workflow(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.states_in_set("request", "terminal") == ["superseded", "archived"]
    assert cfg.states_in_set("task", "initial") == ["draft", "ready"]
    assert cfg.states_in_set("task", "initial", "review_heavy") == ["draft", "review", "ready"]
    assert cfg.state_in_set("task", "archived", "terminal")
    assert not cfg.state_in_set("task", "in_progress", "terminal")


def test_kind_aliases_are_loaded_from_config(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.normalize_kind("req") == "request"
    assert cfg.normalize_kind("specification") == "spec"
    assert cfg.normalize_kind("work-package") == "wp"


def test_reference_inheritance_generic_accessor_supports_standard_refs(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.reference_inheritance("task", "standard_refs") == cfg.standard_refs_inheritance("task")


def test_planning_schema_rejects_unknown_top_level_keys(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    planning_path = root / ".audiagentic" / "planning" / "config" / "planning.yaml"
    payload = yaml.safe_load(planning_path.read_text(encoding="utf-8"))
    payload["planning"]["oops_typo"] = True
    planning_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("planning.yaml" in error and "oops_typo" in error for error in errors)


def test_planning_schema_requires_core_dir_keys(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    planning_path = root / ".audiagentic" / "planning" / "config" / "planning.yaml"
    payload = yaml.safe_load(planning_path.read_text(encoding="utf-8"))
    del payload["planning"]["dirs"]["base"]
    planning_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("planning.yaml" in error and "'base' is a required property" in error for error in errors)


def test_planning_schema_allows_extra_named_dirs_if_string(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    planning_path = root / ".audiagentic" / "planning" / "config" / "planning.yaml"
    payload = yaml.safe_load(planning_path.read_text(encoding="utf-8"))
    payload["planning"]["dirs"]["snapshots"] = ".audiagentic/planning/snapshots"
    planning_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    assert cfg.validate() == []


def test_profiles_schema_rejects_string_on_create_entries(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    profiles_path = root / ".audiagentic" / "planning" / "config" / "profiles.yaml"
    payload = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    payload["planning"]["profiles"]["feature"]["on_create"] = ["specification"]
    profiles_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("profiles.yaml" in error and "'specification' is not of type 'object'" in error for error in errors)


def test_profiles_schema_rejects_unknown_top_level_keys(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    profiles_path = root / ".audiagentic" / "planning" / "config" / "profiles.yaml"
    payload = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    payload["planning"]["typo_bucket"] = {}
    profiles_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("profiles.yaml" in error and "typo_bucket" in error for error in errors)


def test_profiles_schema_rejects_unknown_profile_keys(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    profiles_path = root / ".audiagentic" / "planning" / "config" / "profiles.yaml"
    payload = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    payload["planning"]["profiles"]["feature"]["typo_flag"] = True
    profiles_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("profiles.yaml" in error and "typo_flag" in error for error in errors)


def test_state_model_schema_rejects_unknown_top_level_keys(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    workflows_path = root / ".audiagentic" / "planning" / "config" / "workflows.yaml"
    payload = yaml.safe_load(workflows_path.read_text(encoding="utf-8"))
    payload["planning"]["typo_flow"] = {}
    workflows_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("workflows.yaml" in error and "typo_flow" in error for error in errors)


def test_state_model_schema_rejects_unknown_workflow_group_keys(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    workflows_path = root / ".audiagentic" / "planning" / "config" / "workflows.yaml"
    payload = yaml.safe_load(workflows_path.read_text(encoding="utf-8"))
    payload["planning"]["workflows"]["request"]["typo_group"] = True
    workflows_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("workflows.yaml" in error and "typo_group" in error for error in errors)


def test_documentation_schema_rejects_unknown_top_level_keys(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    doc_path = root / ".audiagentic" / "planning" / "config" / "documentation.yaml"
    payload = yaml.safe_load(doc_path.read_text(encoding="utf-8"))
    payload["planning"]["typo_docs"] = True
    doc_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("documentation.yaml" in error and "typo_docs" in error for error in errors)


def test_documentation_schema_rejects_unknown_surface_keys(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    doc_path = root / ".audiagentic" / "planning" / "config" / "documentation.yaml"
    payload = yaml.safe_load(doc_path.read_text(encoding="utf-8"))
    payload["planning"]["documentation"]["surfaces"][0]["typo_flag"] = True
    doc_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("documentation.yaml" in error and "typo_flag" in error for error in errors)


def test_automations_schema_rejects_unknown_top_level_keys(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    path = root / ".audiagentic" / "planning" / "config" / "automations.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["planning"]["typo_automations"] = True
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("automations.yaml" in error and "typo_automations" in error for error in errors)


def test_automations_schema_rejects_unknown_action_keys(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    path = root / ".audiagentic" / "planning" / "config" / "automations.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["planning"]["automations"][0]["do"][0]["typo_field"] = True
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("automations.yaml" in error and "typo_field" in error for error in errors)


def test_profile_pack_schema_rejects_unknown_keys(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    pack_path = root / ".audiagentic" / "planning" / "config" / "profile-packs" / "standard.yaml"
    payload = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    payload["profile_pack"]["typo_pack"] = True
    pack_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    errors = cfg.validate()
    assert any("profile-packs/standard.yaml" in error and "typo_pack" in error for error in errors)


def test_profile_pack_schema_accepts_open_required_update_kind_map(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    pack_path = root / ".audiagentic" / "planning" / "config" / "profile-packs" / "standard.yaml"
    payload = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    payload["profile_pack"]["documentation"]["required_updates"]["action"] = ["ops-notes"]
    pack_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = Config(root)
    assert cfg.validate() == []
