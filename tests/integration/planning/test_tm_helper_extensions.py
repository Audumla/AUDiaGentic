from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tools.planning.tm_helper as tm

PLANNING_CONFIG_SRC = ROOT / ".audiagentic" / "planning" / "config"


def _seed_helper_project(root: Path) -> None:
    config_dir = root / ".audiagentic" / "planning" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    for rel in ("ids", "indexes", "events", "claims", "meta"):
        (root / ".audiagentic" / "planning" / rel).mkdir(parents=True, exist_ok=True)

    for f in PLANNING_CONFIG_SRC.glob("*.yaml"):
        shutil.copy(f, config_dir / f.name)

    profile_pack_src = PLANNING_CONFIG_SRC / "profile-packs"
    if profile_pack_src.exists():
        shutil.copytree(profile_pack_src, config_dir / "profile-packs")

    for d in ("requests", "specifications", "plans", "tasks/core", "work-packages/core", "standards"):
        (root / "docs" / "planning" / d).mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def helper_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from audiagentic.planning.app.api import PlanningAPI

    _seed_helper_project(tmp_path)
    monkeypatch.setattr(tm, "_ROOT", tmp_path)
    monkeypatch.setattr(tm, "_api", PlanningAPI(tmp_path))
    return tmp_path


def test_tm_helper_lists_documentation_surfaces() -> None:
    surfaces = tm.list_doc_surfaces()
    assert surfaces
    assert any(surface["id"] == "readme" for surface in surfaces)
    assert any("seed_on_install" in surface for surface in surfaces)


def test_tm_helper_lists_request_profiles() -> None:
    profiles = tm.list_request_profiles()
    assert {profile["id"] for profile in profiles} >= {"feature", "issue"}


def test_tm_helper_get_request_profile() -> None:
    profile = tm.get_request_profile("feature")
    assert profile is not None
    assert profile["label"] == "Feature request"


def test_tm_helper_new_request_uses_profile_defaults(helper_project: Path) -> None:
    request = tm.new_request(
        "Improve intake",
        "Create richer request templates",
        source="test",
        profile="feature",
    )
    body = tm.get_content(request["id"])
    shown = tm.show(request["id"])

    assert shown["current_understanding"].startswith("Initial feature intake captured")
    assert shown["open_questions"]
    assert shown["meta"]["request_type"] == "feature"
    assert "# Problem" in body
    assert "# Desired Outcome" in body
    assert "# Open Questions" in body


def test_tm_helper_new_request_persists_source_and_context(helper_project: Path) -> None:
    request = tm.new_request(
        "Trace helper request",
        "Capture provenance",
        source="helper",
        context="unit test",
    )
    shown = tm.show(request["id"])

    assert shown["source"] == "helper"
    assert shown["context"] == "unit test"


def test_tm_helper_head_returns_lean_metadata(helper_project: Path) -> None:
    request = tm.new_request("Lean head", "Return index-only metadata", source="test")
    result = tm.head(request["id"])
    assert result["id"] == request["id"]
    assert result["kind"] == "request"
    assert "path" in result


def test_tm_helper_extract_can_skip_body_and_disk_write(helper_project: Path) -> None:
    request = tm.new_request("Extract request", "Support lean extract", source="test")
    spec = tm.new_spec("Extract controls", "Support lean extract", [request["id"]])
    tm.update_content(spec["id"], "# Purpose\n\nSpec body.\n", mode="replace")
    result = tm.extract(spec["id"], include_body=False, write_to_disk=False)
    cache = helper_project / ".audiagentic" / "planning" / "extracts" / f"{spec['id']}.json"
    assert "body" not in result
    assert not cache.exists()


def test_tm_helper_doc_sync_queries() -> None:
    requirements = tm.get_doc_sync_requirements("task", "standard")
    assert requirements["required_updates"] == ["changelog"]
    assert "task" in requirements["all_required_updates"]
    assert tm.pending_doc_updates("wp", "standard") == ["changelog", "readme"]


def test_tm_helper_lists_support_docs_and_references() -> None:
    support_docs = tm.list_support_docs()
    reference_docs = tm.list_reference_docs()
    assert any(doc["id"] == "support-0001" for doc in support_docs)
    assert any(doc["label"] == "planning-request-profiles" for doc in reference_docs)


def test_tm_helper_get_subsection_supports_dot_and_slash_paths(helper_project: Path) -> None:
    request = tm.new_request("Section parsing request", "Supports helper task creation", source="test")
    spec = tm.new_spec("Section parsing spec", "Supports helper task creation", [request["id"]])
    content = """# Description

Top level body.

## Notes

Nested notes.

#### Deep Detail

Deep content.
"""
    item = tm.create_with_content(
        "task",
        label="Nested subsection test",
        summary="Exercise subsection parsing",
        content=content,
        spec=spec["id"],
    )

    slash_result = tm.get_subsection(item["id"], "description/notes")
    dot_result = tm.get_subsection(item["id"], "description.notes")
    deep_result = tm.get_subsection(item["id"], "description.notes.deep detail")

    assert slash_result["found"] is True
    assert slash_result["content"] == "Nested notes.\n\n#### Deep Detail\n\nDeep content."
    assert dot_result["found"] is True
    assert dot_result["content"] == slash_result["content"]
    assert deep_result["found"] is True
    assert deep_result["content"] == "Deep content."


def test_tm_helper_new_item_reference_validation_rejects_missing_refs(helper_project: Path) -> None:
    with pytest.raises(ValueError, match="spec requires at least one request reference"):
        tm.new_spec("Missing request spec", "Should fail")

    with pytest.raises(ValueError, match="spec 'spec-9999' does not exist"):
        tm.new_plan("Missing spec plan", "Should fail", spec="spec-9999")

    with pytest.raises(ValueError, match="spec 'spec-9999' does not exist"):
        tm.new_task("Missing spec task", "Should fail", spec="spec-9999")

    with pytest.raises(ValueError, match="plan 'plan-9999' does not exist"):
        tm.new_wp("Missing plan wp", "Should fail", plan="plan-9999")


def test_tm_helper_verify_structure_marks_optional_extensions_non_blocking(helper_project: Path) -> None:
    result = tm.verify_structure()

    assert result["healthy"] is True
    assert result["checks"]["config_profiles"]["required"] is False
    assert result["checks"]["config_documentation"]["required"] is False
    assert "PASSED" in result["summary"]


def test_tm_helper_verify_structure_reports_required_failures_clearly(helper_project: Path) -> None:
    planning_config = helper_project / ".audiagentic" / "planning" / "config" / "planning.yaml"
    planning_config.unlink()

    result = tm.verify_structure()

    assert result["healthy"] is False
    assert result["checks"]["config_planning"]["ok"] is False
    assert result["summary"].startswith("Structure check FAILED:")


def test_tm_helper_lists_and_gets_standards(helper_project: Path) -> None:
    standard = tm.new_standard("Review findings standard", "Keeps review output consistent")
    tm.update_content(
        standard["id"],
        "# Standard\n\n# Requirements\n\n1. Findings first.\n",
        mode="replace",
    )

    standards = tm.list_standards()
    assert any(item["id"] == standard["id"] for item in standards)

    standard_doc = tm.get_standard(standard["id"])
    assert standard_doc["item"]["kind"] == "standard"
    assert "Findings first." in standard_doc["body"]


def test_tm_helper_plan_and_task_request_refs_appear_in_trace_index(
    helper_project: Path,
) -> None:
    request = tm.new_request("Trace request", "Track reverse refs", source="test")
    spec = tm.new_spec("Trace spec", "Trace spec summary", [request["id"]])
    plan = tm.new_plan("Trace plan", "Trace plan summary", spec["id"], [request["id"]])
    task = tm.new_task(
        "Trace task",
        "Trace task summary",
        spec["id"],
        request_refs=[request["id"]],
    )

    trace = json.loads(
        (helper_project / ".audiagentic" / "planning" / "indexes" / "trace.json").read_text(
            encoding="utf-8"
        )
    )
    request_edges = [
        ref for ref in trace["refs"] if ref["field"] == "request_refs" and ref["dst"] == request["id"]
    ]
    assert any(ref["src"] == spec["id"] for ref in request_edges)
    assert any(ref["src"] == plan["id"] for ref in request_edges)
    assert any(ref["src"] == task["id"] for ref in request_edges)


def test_tm_helper_new_spec_updates_request_spec_refs(helper_project: Path) -> None:
    request = tm.new_request("Spec backref request", "Track spec refs on request", source="test")
    spec = tm.new_spec("Spec backref spec", "Trace back to request", [request["id"]])

    shown = tm.show(request["id"])

    assert spec["id"] in shown.get("spec_refs", [])


def test_tm_helper_delete_and_list_include_deleted(helper_project: Path) -> None:
    request = tm.new_request("Delete request", "Delete summary", source="test")
    spec = tm.new_spec("Delete spec", "Delete summary", [request["id"]])
    task = tm.new_task("Delete task", "Delete summary", spec["id"])

    result = tm.delete(task["id"], reason="test cleanup")
    assert result["hard_delete"] is False

    active_ids = {item["id"] for item in tm.list_kind("task")}
    all_ids = {item["id"] for item in tm.list_kind("task", include_deleted=True)}
    shown = tm.show(task["id"])

    assert task["id"] not in active_ids
    assert task["id"] in all_ids
    assert shown["deleted"] is True


def test_tm_helper_state_supports_archive_metadata_and_list_filtering(
    helper_project: Path,
) -> None:
    request = tm.new_request("Archive request", "Archive summary", source="test")
    spec = tm.new_spec("Archive spec", "Archive summary", [request["id"]])
    task = tm.new_task("Archive task", "Archive summary", spec["id"])

    archived = tm.state(task["id"], "archived", reason="superseded", actor="tester")
    shown = tm.show(task["id"])
    active_ids = {item["id"] for item in tm.list_kind("task")}
    all_ids = {item["id"] for item in tm.list_kind("task", include_archived=True)}

    assert archived["state"] == "archived"
    assert archived["archived_by"] == "tester"
    assert archived["archive_reason"] == "superseded"
    assert shown["archived_at"] is not None
    assert task["id"] not in active_ids
    assert task["id"] in all_ids
