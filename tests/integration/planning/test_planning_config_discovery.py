"""Integration tests for planning_config_summary (request-30 / tm_docs op=config)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tools.planning.tm_helper as tm
from tests.planning_testkit import seed_planning_config

KNOWN_KINDS = {"request", "spec", "plan", "task", "wp", "standard"}


def _seed_root(tmp_path: Path) -> Path:
    seed_planning_config(tmp_path)
    return tmp_path


def test_compact_contains_top_level_defaults(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="compact", root=root)
    assert "default_profile" in result
    assert "default_guidance" in result
    assert isinstance(result["default_profile"], str)
    assert isinstance(result["default_guidance"], str)


def test_compact_lists_all_kinds(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="compact", root=root)
    assert set(result["kinds"].keys()) >= KNOWN_KINDS


def test_compact_per_kind_shape(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="compact", root=root)
    for k, entry in result["kinds"].items():
        assert "has_domain" in entry, f"{k} missing has_domain"
        assert "required_fields" in entry, f"{k} missing required_fields"
        assert "optional_fields" in entry, f"{k} missing optional_fields"
        assert "required_refs" in entry, f"{k} missing required_refs"
        assert "required_sections" in entry, f"{k} missing required_sections"
        assert "state_on_create" in entry, f"{k} missing state_on_create"
        assert "usage" in entry, f"{k} missing usage"


def test_compact_task_has_domain_and_spec_ref(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="compact", kind="task", root=root)
    task = result["kinds"]["task"]
    assert task["has_domain"] is True
    assert "spec" in task["required_refs"]
    assert "domain='<domain>'" in task["usage"]
    assert "refs={'spec': '<id>'}" in task["usage"]


def test_compact_request_no_domain_no_required_refs(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="compact", kind="request", root=root)
    req = result["kinds"]["request"]
    assert req["has_domain"] is False
    assert req["required_refs"] == []


def test_compact_profiles_and_guidance_lists(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="compact", root=root)
    assert isinstance(result["profiles"], list)
    assert len(result["profiles"]) > 0
    assert isinstance(result["guidance_levels"], list)
    assert len(result["guidance_levels"]) > 0


def test_compact_kind_filter_returns_single_kind(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="compact", kind="spec", root=root)
    assert list(result["kinds"].keys()) == ["spec"]


def test_compact_no_relationship_rules(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="compact", root=root)
    for entry in result["kinds"].values():
        assert "relationship_rules" not in entry


def test_full_includes_relationship_rules(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="full", root=root)
    for k, entry in result["kinds"].items():
        assert "relationship_rules" in entry, f"{k} missing relationship_rules in full mode"


def test_full_includes_default_references(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="full", root=root)
    for k, entry in result["kinds"].items():
        assert "default_references" in entry, f"{k} missing default_references in full mode"


def test_full_includes_template_sections(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="full", root=root)
    for k, entry in result["kinds"].items():
        assert "template_sections" in entry, f"{k} missing template_sections in full mode"
        assert isinstance(entry["template_sections"], list)


def test_full_includes_profiles_detail(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    result = tm.planning_config_summary(mode="full", root=root)
    assert "profiles_detail" in result
    assert "guidance_levels_detail" in result


def test_invalid_kind_raises(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    try:
        tm.planning_config_summary(mode="compact", kind="bogus", root=root)
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "bogus" in str(e)


def test_output_matches_live_config(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    from audiagentic.planning.app.config import Config
    cfg = Config(root)
    result = tm.planning_config_summary(mode="compact", root=root)
    assert result["default_profile"] == cfg.default_profile()
    assert result["default_guidance"] == cfg.default_guidance()
    task_entry = result["kinds"]["task"]
    assert task_entry["has_domain"] == cfg.kind_has_domain("task")
    assert task_entry["required_refs"] == cfg.kind_required_refs("task")
