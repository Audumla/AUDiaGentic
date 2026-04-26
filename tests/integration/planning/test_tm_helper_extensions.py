from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
import tools.planning.tm_helper as tm
from tests.planning_testkit import seed_planning_config


def _seed_helper_project(root: Path) -> None:
    seed_planning_config(root)
    for rel in ("ids", "indexes", "events", "claims", "meta"):
        (root / ".audiagentic" / "planning" / rel).mkdir(parents=True, exist_ok=True)

    for d in (
        "requests",
        "specifications",
        "plans",
        "tasks/core",
        "work-packages/core",
        "standards",
        "supporting",
    ):
        (root / "docs" / "planning" / d).mkdir(parents=True, exist_ok=True)
    (root / "docs" / "references").mkdir(parents=True, exist_ok=True)
    (
        root / "docs" / "planning" / "supporting" / "support-0001-doc-surfaces-analysis.md"
    ).write_text(
        "---\n"
        "id: support-0001\n"
        "label: Documentation surfaces analysis\n"
        "role: analysis\n"
        "status: active\n"
        "supports:\n"
        "  - spec-0001\n"
        "owner: wp-0001\n"
        "used_by:\n"
        "  - task-0001\n"
        "---\n\n"
        "# Analysis\n\nSeed support doc.\n",
        encoding="utf-8",
    )
    (root / "docs" / "references" / "planning-guide.md").write_text(
        "# Planning Guide\n",
        encoding="utf-8",
    )


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


def test_tm_helper_lists_creation_profiles() -> None:
    profiles = tm.list_creation_profiles()
    assert {profile["id"] for profile in profiles} >= {"feature", "issue"}


def test_tm_helper_get_creation_profile() -> None:
    profile = tm.get_creation_profile("feature")
    assert profile is not None
    assert profile["label"] == "Feature request"


def test_tm_helper_new_request_uses_profile_defaults(helper_project: Path) -> None:
    request = tm.create(
        "request",
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
    request = tm.create(
        "request",
        "Trace helper request",
        "Capture provenance",
        source="helper",
        context="unit test",
    )
    shown = tm.show(request["id"])

    assert shown["source"] == "helper"
    assert shown["context"] == "unit test"


def test_tm_helper_head_returns_lean_metadata(helper_project: Path) -> None:
    request = tm.create("request", "Lean head", "Return index-only metadata", source="test")
    result = tm.head(request["id"])
    assert result["id"] == request["id"]
    assert result["kind"] == "request"
    assert "path" in result


def test_tm_helper_extract_can_skip_body_and_disk_write(helper_project: Path) -> None:
    request = tm.create("request", "Extract request", "Support lean extract", source="test")
    spec = tm.create(
        "spec",
        "Extract controls",
        "Support lean extract",
        refs={"request_refs": [request["id"]]},
    )
    tm.update_content(spec["id"], "# Purpose\n\nSpec body.\n", mode="replace")
    cache = helper_project / ".audiagentic" / "planning" / "extracts" / f"{spec['id']}.json"
    before = cache.stat().st_mtime_ns if cache.exists() else None
    result = tm.extract(spec["id"], include_body=False, write_to_disk=False)
    assert "body" not in result
    after = cache.stat().st_mtime_ns if cache.exists() else None
    assert after == before


def test_tm_helper_doc_sync_queries() -> None:
    requirements = tm.get_doc_sync_requirements("task", "standard")
    assert requirements["required_updates"] == ["changelog"]
    assert "task" in requirements["all_required_updates"]
    assert tm.pending_doc_updates("wp", "standard") == ["changelog", "readme"]


def test_tm_helper_lists_support_docs_and_references() -> None:
    support_docs = tm.list_support_docs()
    reference_docs = tm.list_reference_docs()
    assert any(doc["id"] == "support-0001" for doc in support_docs)
    assert isinstance(reference_docs, list)
    if reference_docs:
        assert all("label" in doc and "path" in doc for doc in reference_docs)


def test_tm_helper_get_subsection_supports_dot_and_slash_paths(helper_project: Path) -> None:
    request = tm.create(
        "request", "Section parsing request", "Supports helper task creation", source="test"
    )
    spec = tm.create(
        "spec",
        "Section parsing spec",
        "Supports helper task creation",
        refs={"request_refs": [request["id"]]},
    )
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
        refs={"spec": spec["id"]},
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
    with pytest.raises(ValueError, match="requires 'request_refs' reference"):
        tm.create("spec", "Missing request spec", "Should fail")

    with pytest.raises(ValueError, match="Missing required reference: spec_refs"):
        tm.create("plan", "Missing spec plan", "Should fail")

    with pytest.raises(ValueError, match="requires 'spec' reference"):
        tm.create("task", "Missing spec task", "Should fail")

    with pytest.raises(ValueError, match="requires 'plan' reference"):
        tm.create("wp", "Missing plan wp", "Should fail")


def test_tm_helper_verify_structure_marks_optional_extensions_non_blocking(helper_project: Path) -> None:
    result = tm.verify_structure(helper_project)

    assert result["healthy"] is True
    assert result["checks"]["config_profiles"]["required"] is False
    assert result["checks"]["config_documentation"]["required"] is False
    assert "PASSED" in result["summary"]


def test_tm_helper_verify_structure_uses_explicit_root(helper_project: Path) -> None:
    result = tm.verify_structure(helper_project)
    assert result["root"] == str(helper_project)


def test_tm_helper_verify_structure_reports_required_failures_clearly(helper_project: Path) -> None:
    planning_config = helper_project / ".audiagentic" / "planning" / "config" / "planning.yaml"
    planning_config.unlink()

    result = tm.verify_structure(helper_project)

    assert result["healthy"] is False
    assert result["checks"]["config_planning"]["ok"] is False
    assert result["summary"].startswith("Structure check FAILED:")


def test_tm_helper_lists_and_gets_standards(helper_project: Path) -> None:
    standard = tm.create("standard", "Review findings standard", "Keeps review output consistent")
    tm.update_content(
        standard["id"],
        "# Standard\n\n# Requirements\n\n1. Findings first.\n",
        mode="replace",
    )

    standards = tm.list_kind("standard")
    assert any(item["id"] == standard["id"] for item in standards)

    standard_doc = tm.extract(standard["id"])
    assert standard_doc["item"]["kind"] == "standard"
    assert "Findings first." in standard_doc["body"]


def test_tm_helper_plan_and_task_request_refs_appear_in_trace_index(
    helper_project: Path,
) -> None:
    request = tm.create("request", "Trace request", "Track reverse refs", source="test")
    spec = tm.create(
        "spec", "Trace spec", "Trace spec summary", refs={"request_refs": [request["id"]]}
    )
    plan = tm.create(
        "plan",
        "Trace plan",
        "Trace plan summary",
        refs={"spec": spec["id"], "request_refs": [request["id"]]},
    )
    task = tm.create(
        "task",
        "Trace task",
        "Trace task summary",
        refs={"spec": spec["id"], "request_refs": [request["id"]]},
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
    request = tm.create("request", "Spec backref request", "Track spec refs on request", source="test")
    spec = tm.create(
        "spec",
        "Spec backref spec",
        "Trace back to request",
        refs={"request_refs": [request["id"]]},
    )

    shown = tm.show(request["id"])

    assert spec["id"] in shown.get("spec_refs", [])


def test_tm_helper_delete_and_list_include_deleted(helper_project: Path) -> None:
    request = tm.create("request", "Delete request", "Delete summary", source="test")
    spec = tm.create("spec", "Delete spec", "Delete summary", refs={"request_refs": [request["id"]]})
    task = tm.create("task", "Delete task", "Delete summary", refs={"spec": spec["id"]})

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
    request = tm.create("request", "Archive request", "Archive summary", source="test")
    spec = tm.create("spec", "Archive spec", "Archive summary", refs={"request_refs": [request["id"]]})
    task = tm.create("task", "Archive task", "Archive summary", refs={"spec": spec["id"]})

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
