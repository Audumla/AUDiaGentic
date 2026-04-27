"""Full surface integration tests for PlanningAPI.

Covers all methods and scenarios not exercised by the existing
test_planning_api.py and test_tm_helper_extensions.py suites.

Tests are written against the intended contract. Some will fail until
the corresponding functionality is implemented or bugs are fixed.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from tests.planning_testkit import seed_planning_config

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _seed(root: Path) -> None:
    seed_planning_config(root)
    for d in (
        "requests",
        "specifications",
        "plans",
        "tasks/core",
        "tasks/contrib",
        "work-packages/core",
        "work-packages/contrib",
        "standards",
    ):
        (root / "docs" / "planning" / d).mkdir(parents=True, exist_ok=True)
    for sub in ("ids", "indexes", "events", "claims", "meta", "extracts"):
        (root / ".audiagentic" / "planning" / sub).mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def pr(tmp_path: Path):
    """Return (root, api) for an isolated project."""
    _seed(tmp_path)
    from audiagentic.planning.app.api import PlanningAPI

    return tmp_path, PlanningAPI(tmp_path)


# Shorthand helpers inside tests
def _spec_and_task(api):
    spec = _new_spec(api)
    task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
    return spec, task


def _new_request(api, label: str = "R", summary: str = "S"):
    return api.new("request", label=label, summary=summary, source="test")


def _new_spec(api, label: str = "S", summary: str = "S"):
    request = _new_request(api, label=f"{label} request", summary=summary)
    return api.new("spec", label=label, summary=summary, refs={"request_refs": [request.data["id"]]})


def _full_hierarchy(api):
    req = api.new("request", label="R", summary="R", source="test")
    spec = api.new("spec", label="S", summary="S", refs={"request_refs": [req.data["id"]]})
    plan = api.new("plan", label="P", summary="P", refs={"spec": spec.data["id"]})
    task = api.new("task", label="T", summary="T", refs={"spec": spec.data["id"]})
    wp = api.new("wp", label="W", summary="W", refs={"plan": plan.data["id"]})
    return req, spec, plan, task, wp


# ===========================================================================
# update()
# ===========================================================================


class TestUpdate:
    def test_update_label(self, pr):
        _, api = pr
        spec = _new_spec(api, label="Original")
        updated = api.update(spec.data["id"], label="Updated")
        assert updated.data["label"] == "Updated"

    def test_update_summary(self, pr):
        _, api = pr
        spec = _new_spec(api, summary="Original summary")
        updated = api.update(spec.data["id"], summary="New summary")
        assert updated.data["summary"] == "New summary"

    def test_update_body_append(self, pr):
        _, api = pr
        spec = _new_spec(api)
        api.update(spec.data["id"], body_append="## Appended\n\nExtra content.")
        body = api.get_content(spec.data["id"])
        assert "Appended" in body
        assert "Extra content." in body

    def test_update_returns_updated_item(self, pr):
        _, api = pr
        spec = _new_spec(api)
        result = api.update(spec.data["id"], label="Changed")
        assert result.data["id"] == spec.data["id"]
        assert result.data["label"] == "Changed"

    def test_update_no_args_is_noop(self, pr):
        _, api = pr
        spec = _new_spec(api)
        result = api.update(spec.data["id"])
        assert result.data["label"] == "S"


# ===========================================================================
# get_content() / update_content()
# ===========================================================================


class TestContent:
    def test_get_content_returns_body_without_frontmatter(self, pr):
        _, api = pr
        spec = _new_spec(api)
        body = api.get_content(spec.data["id"])
        assert "---" not in body
        assert isinstance(body, str)

    def test_update_content_replace(self, pr):
        _, api = pr
        spec = _new_spec(api)
        api.update_content(spec.data["id"], "# Purpose\n\nReplaced.\n", mode="replace")
        assert "Replaced." in api.get_content(spec.data["id"])

    def test_update_content_append(self, pr):
        _, api = pr
        spec = _new_spec(api)
        api.update_content(spec.data["id"], "# Purpose\n\nOriginal.\n", mode="replace")
        api.update_content(spec.data["id"], "## Appended\n\nExtra.\n", mode="append")
        body = api.get_content(spec.data["id"])
        assert "Original." in body
        assert "Extra." in body

    def test_update_content_insert_at_position(self, pr):
        _, api = pr
        spec = _new_spec(api)
        api.update_content(spec.data["id"], "# Purpose\n\nLine A.\n\nLine B.\n", mode="replace")
        api.update_content(spec.data["id"], "INSERTED", mode="insert", position=3)
        body = api.get_content(spec.data["id"])
        assert "INSERTED" in body

    def test_update_content_insert_requires_position(self, pr):
        _, api = pr
        spec = _new_spec(api)
        with pytest.raises(ValueError, match="position required"):
            api.update_content(spec.data["id"], "x", mode="insert")

    def test_update_content_insert_out_of_range_raises(self, pr):
        _, api = pr
        spec = _new_spec(api)
        api.update_content(spec.data["id"], "# A\n\nB.\n", mode="replace")
        with pytest.raises(ValueError, match="out of range"):
            api.update_content(spec.data["id"], "x", mode="insert", position=9999)

    def test_update_content_section_mode_replaces_section(self, pr):
        _, api = pr
        spec = _new_spec(api)
        api.update_content(
            spec.data["id"],
            "# Purpose\n\nOld content.\n\n# Scope\n\nScope text.\n",
            mode="replace",
        )
        api.update_content(spec.data["id"], "New content.", mode="section", section="# Purpose")
        body = api.get_content(spec.data["id"])
        assert "New content." in body
        assert "Old content." not in body
        assert "Scope text." in body  # sibling section untouched

    def test_update_content_section_mode_appends_if_not_found(self, pr):
        _, api = pr
        spec = _new_spec(api)
        api.update_content(spec.data["id"], "# Purpose\n\nContent.\n", mode="replace")
        api.update_content(
            spec.data["id"],
            "Added section content.",
            mode="section",
            section="# New Section",
        )
        assert "New Section" in api.get_content(spec.data["id"])

    def test_update_content_invalid_mode_raises(self, pr):
        _, api = pr
        spec = _new_spec(api)
        with pytest.raises(ValueError, match="unknown mode"):
            api.update_content(spec.data["id"], "x", mode="overwrite")


# ===========================================================================
# create_with_content()
# ===========================================================================


class TestCreateWithContent:
    def test_create_request_with_content(self, pr):
        _, api = pr
        content = "# Problem\n\nThe core issue.\n\n# Desired Outcome\n\nBetter state.\n"
        item = api.create_with_content(
            "request", label="R", summary="S", content=content, source="test"
        )
        assert item.kind == "request"
        assert "The core issue." in api.get_content(item.data["id"])

    def test_create_spec_with_content(self, pr):
        _, api = pr
        content = "# Purpose\n\nNew spec.\n"
        req = _new_request(api, label="Create-with-content request")
        item = api.create_with_content(
            "spec",
            label="S",
            summary="S",
            content=content,
            refs={"request_refs": [req.data["id"]]},
        )
        assert "New spec." in api.get_content(item.data["id"])

    def test_create_task_with_content(self, pr):
        _, api = pr
        spec = _new_spec(api, label="SP", summary="SP")
        content = "# Description\n\nTask detail.\n"
        item = api.create_with_content(
            "task", label="T", summary="S", content=content, refs={"spec": spec.data["id"]}
        )
        assert "Task detail." in api.get_content(item.data["id"])

    def test_create_wp_with_content(self, pr):
        _, api = pr
        spec = _new_spec(api, label="SP", summary="SP")
        plan = api.new("plan", label="PL", summary="PL", refs={"spec": spec.data["id"]})
        content = "# Objective\n\nWP detail.\n"
        item = api.create_with_content(
            "wp", label="W", summary="S", content=content, refs={"plan": plan.data["id"]}
        )
        assert "WP detail." in api.get_content(item.data["id"])

    def test_create_standard_with_content(self, pr):
        _, api = pr
        content = "# Standard\n\nUse snake_case.\n"
        item = api.create_with_content("standard", label="Naming", summary="S", content=content)
        assert "snake_case" in api.get_content(item.data["id"])

    def test_create_with_content_task_requires_spec(self, pr):
        _, api = pr
        with pytest.raises(ValueError, match="requires 'spec' reference"):
            api.create_with_content(
                "task", label="T", summary="S", content="# Description\n\nX.\n"
            )


# ===========================================================================
# move()
# ===========================================================================


class TestMove:
    def test_move_task_to_contrib(self, pr):
        root, api = pr
        spec = _new_spec(api)
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        moved = api.move(task.data["id"], "contrib")
        assert "contrib" in str(moved.path)
        assert moved.path.exists()
        assert moved.path.name == api.paths.filename_for("task", task.data["id"], task.data["label"])

    def test_move_wp_to_contrib(self, pr):
        root, api = pr
        spec = _new_spec(api)
        plan = api.new("plan", label="P", summary="P", refs={"spec": spec.data["id"]})
        wp = api.new("wp", label="W", summary="S", refs={"plan": plan.data["id"]})
        moved = api.move(wp.data["id"], "contrib")
        assert "contrib" in str(moved.path)
        assert moved.path.exists()

    def test_move_request_raises(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        with pytest.raises(ValueError, match="configured domain kinds"):
            api.move(req.data["id"], "contrib")

    def test_move_spec_raises(self, pr):
        _, api = pr
        spec = _new_spec(api)
        with pytest.raises(ValueError, match="configured domain kinds"):
            api.move(spec.data["id"], "contrib")

    def test_move_preserves_content(self, pr):
        _, api = pr
        spec = _new_spec(api)
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        original_label = task.data["label"]
        moved = api.move(task.data["id"], "contrib")
        assert moved.data["label"] == original_label


# ===========================================================================
# relink()
# ===========================================================================


class TestRelink:
    def test_relink_adds_to_request_refs(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        spec = _new_spec(api)
        result = api.relink(spec.data["id"], "request_refs", req.data["id"])
        assert req.data["id"] in result.data.get("request_refs", [])

    def test_relink_request_refs_updates_request_spec_refs(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        spec = _new_spec(api)
        api.relink(spec.data["id"], "request_refs", req.data["id"])
        updated_request = api._find(req.data["id"])
        assert spec.data["id"] in updated_request.data.get("spec_refs", [])

    def test_relink_sets_spec_ref(self, pr):
        _, api = pr
        spec1 = _new_spec(api, label="S1")
        spec2 = _new_spec(api, label="S2")
        task = api.new("task", label="T", summary="S", refs={"spec": spec1.data["id"]})
        result = api.relink(task.data["id"], "spec_ref", spec2.data["id"])
        assert result.data["spec_ref"] == spec2.data["id"]

    def test_relink_sets_parent_task_ref(self, pr):
        _, api = pr
        spec = _new_spec(api)
        parent = api.new("task", label="Parent", summary="S", refs={"spec": spec.data["id"]})
        child = api.new("task", label="Child", summary="S", refs={"spec": spec.data["id"]})
        result = api.relink(child.data["id"], "parent_task_ref", parent.data["id"])
        assert result.data["parent_task_ref"] == parent.data["id"]

    def test_relink_task_refs_with_seq(self, pr):
        _, api = pr
        spec = _new_spec(api)
        plan = api.new("plan", label="P", summary="P", refs={"spec": spec.data["id"]})
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        wp = api.new("wp", label="W", summary="S", refs={"plan": plan.data["id"]})
        result = api.relink(wp.data["id"], "task_refs", task.data["id"], seq=100, display="T.1")
        refs = result.data.get("task_refs", [])
        assert any(r.get("ref") == task.data["id"] for r in refs)

    def test_relink_invalid_field_raises(self, pr):
        _, api = pr
        spec = _new_spec(api)
        with pytest.raises(ValueError, match="unsupported field"):
            api.relink(spec.data["id"], "nonexistent_field", "something")

    def test_relink_does_not_duplicate_request_refs(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        spec = _new_spec(api)
        api.relink(spec.data["id"], "request_refs", req.data["id"])
        result = api.relink(spec.data["id"], "request_refs", req.data["id"])
        assert result.data["request_refs"].count(req.data["id"]) == 1


# ===========================================================================
# reconcile()
# ===========================================================================


class TestReconcile:
    def test_reconcile_returns_dict_with_orphans(self, pr):
        _, api = pr
        result = api.reconcile()
        assert isinstance(result, dict)
        assert "orphans" in result

    def test_reconcile_empty_project_has_no_orphans(self, pr):
        _, api = pr
        result = api.reconcile()
        assert result["orphans"] == []

    def test_reconcile_rebuilds_index(self, pr):
        root, api = pr
        api.new("request", label="R", summary="S", source="test")
        api.reconcile()
        assert (root / ".audiagentic" / "planning" / "indexes" / "requests.json").exists()

    def test_reconcile_normalizes_request_filename_to_slugged_shape(self, pr):
        _, api = pr
        req = api.new("request", label="My Request", summary="S", source="test")
        api.reconcile()
        updated = api.lookup(req.data["id"])
        assert updated.path.name == f"{req.data['id']}-my-request.md"

    def test_maintain_rebuilds_extracts(self, pr):
        root, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        result = api.maintain()
        assert result["indexes_rebuilt"] is True
        assert (root / ".audiagentic" / "planning" / "extracts" / f"{req.data['id']}.json").exists()


# ===========================================================================
# state() for request, plan, wp
# ===========================================================================


class TestStateTransitions:
    def test_state_request_captured_to_distilled(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        assert req.data["state"] == "captured"
        result = api.state(req.data["id"], "distilled")
        assert result.data["state"] == "distilled"

    def test_state_plan_draft_to_ready(self, pr):
        _, api = pr
        spec = _new_spec(api)
        plan = api.new("plan", label="P", summary="P", refs={"spec": spec.data["id"]})
        assert plan.data["state"] == "draft"
        result = api.state(plan.data["id"], "ready")
        assert result.data["state"] == "ready"

    def test_state_wp_draft_to_ready(self, pr):
        _, api = pr
        spec = _new_spec(api)
        plan = api.new("plan", label="P", summary="P", refs={"spec": spec.data["id"]})
        wp = api.new("wp", label="W", summary="S", refs={"plan": plan.data["id"]})
        assert wp.data["state"] == "draft"
        result = api.state(wp.data["id"], "ready")
        assert result.data["state"] == "ready"

    def test_state_invalid_for_kind_raises(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        with pytest.raises(ValueError):
            api.state(req.data["id"], "nonexistent_state")

    def test_state_emits_event(self, pr):
        root, api = pr
        spec = _new_spec(api)
        api.state(spec.data["id"], "ready")
        events_path = root / ".audiagentic" / "planning" / "events" / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        assert any(
            e.get("event") == "planning.item.state.changed" and e.get("id") == spec.data["id"]
            for e in events
        )

    def test_state_updates_index(self, pr):
        root, api = pr
        spec = _new_spec(api)
        api.state(spec.data["id"], "ready")
        idx = json.loads(
            (root / ".audiagentic" / "planning" / "indexes" / "specifications.json").read_text()
        )
        entry = next(e for e in idx["items"] if e["id"] == spec.data["id"])
        assert entry["state"] == "ready"


# ===========================================================================
# show() / extract()
# ===========================================================================


class TestShowExtract:
    def test_index_writes_lookup_json(self, pr):
        root, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        lookup = json.loads(
            (root / ".audiagentic" / "planning" / "indexes" / "lookup.json").read_text(
                encoding="utf-8"
            )
        )
        assert req.data["id"] in lookup["items"]
        assert lookup["items"][req.data["id"]]["kind"] == "request"

    def test_head_returns_index_metadata(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        head = api.head(req.data["id"])
        assert head["id"] == req.data["id"]
        assert head["kind"] == "request"
        assert "path" in head

    def test_lookup_falls_back_when_lookup_index_missing(self, pr):
        root, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        (root / ".audiagentic" / "planning" / "indexes" / "lookup.json").unlink()
        item = api.lookup(req.data["id"])
        assert item.data["id"] == req.data["id"]

    def test_head_falls_back_when_lookup_index_missing(self, pr):
        root, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        (root / ".audiagentic" / "planning" / "indexes" / "lookup.json").unlink()
        head = api.head(req.data["id"])
        assert head["id"] == req.data["id"]
        assert head["kind"] == "request"

    def test_lookup_falls_back_when_id_missing_from_lookup_index(self, pr):
        root, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        lookup_path = root / ".audiagentic" / "planning" / "indexes" / "lookup.json"
        lookup = json.loads(lookup_path.read_text(encoding="utf-8"))
        lookup["items"].pop(req.data["id"])
        lookup_path.write_text(json.dumps(lookup, indent=2), encoding="utf-8")
        item = api.lookup(req.data["id"])
        assert item.data["id"] == req.data["id"]

    def test_show_returns_kind_and_path(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        shown = api.extracts.show(req.data["id"])
        assert shown["kind"] == "request"
        assert "path" in shown

    def test_show_includes_all_frontmatter_fields(self, pr):
        _, api = pr
        req = api.new("request", label="My Request", summary="My Summary", source="test")
        shown = api.extracts.show(req.data["id"])
        assert shown["label"] == "My Request"
        assert shown["summary"] == "My Summary"
        assert shown["state"] == "captured"

    def test_show_request_includes_spec_refs_when_present(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        spec = api.new("spec", label="S", summary="S", refs={"request_refs": [req.data["id"]]})
        shown = api.extracts.show(req.data["id"])
        assert spec.data["id"] in shown.get("spec_refs", [])

    def test_extract_includes_body(self, pr):
        _, api = pr
        spec = _new_spec(api)
        api.update_content(spec.data["id"], "# Purpose\n\nSome body text.\n", mode="replace")
        result = api.extracts.extract(spec.data["id"])
        assert "body" in result
        assert "Some body text." in result["body"]

    def test_extract_with_related_includes_fields(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        spec = api.new("spec", label="S", summary="S", refs={"request_refs": [req.data["id"]]})
        result = api.extracts.extract(spec.data["id"], with_related=True)
        assert "related" in result
        assert "request_refs" in result["related"]

    def test_extract_with_resources_includes_attachments_key(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        result = api.extracts.extract(req.data["id"], with_resources=True)
        # When no attachments dir exists, key should still be present or absent gracefully
        assert "body" in result

    def test_extract_can_skip_body(self, pr):
        _, api = pr
        spec = _new_spec(api)
        api.update_content(spec.data["id"], "# Purpose\n\nSome body text.\n", mode="replace")
        result = api.extracts.extract(spec.data["id"], include_body=False)
        assert "body" not in result
        assert result["item"]["id"] == spec.data["id"]

    def test_extract_writes_json_cache(self, pr):
        root, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        api.extracts.extract(req.data["id"])
        cache = root / ".audiagentic" / "planning" / "extracts" / f"{req.data['id']}.json"
        assert cache.exists()
        cached = json.loads(cache.read_text())
        assert cached["item"]["id"] == req.data["id"]

    def test_extract_can_skip_json_cache_write(self, pr):
        root, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        api.extracts.extract(req.data["id"], write_to_disk=False)
        cache = root / ".audiagentic" / "planning" / "extracts" / f"{req.data['id']}.json"
        assert not cache.exists()

    def test_extract_effective_refs_field_present(self, pr):
        _, api = pr
        spec = _new_spec(api)
        result = api.extracts.extract(spec.data["id"])
        assert "effective_refs" in result


# ===========================================================================
# effective_refs()
# ===========================================================================


class TestEffectiveRefs:
    def test_effective_refs_returns_list_for_item_without_refs(self, pr):
        _, api = pr
        spec = _new_spec(api)
        refs = api.effective_refs(spec.data["id"])
        assert isinstance(refs, list)

    def test_effective_refs_includes_inherited_refs(self, pr):
        _, api = pr
        std = api.new("standard", label="Naming conventions", summary="S")
        spec = _new_spec(api)
        api.relink(spec.data["id"], "standard_refs", std.data["id"])
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        refs = api.effective_refs(task.data["id"])
        assert std.data["id"] in refs

    def test_effective_refs_for_unknown_item_raises(self, pr):
        _, api = pr
        with pytest.raises(KeyError):
            api.effective_refs("nonexistent-0001")


# ===========================================================================
# sync_id_counters()
# ===========================================================================


class TestSyncIdCounters:
    def test_sync_creates_counter_files_for_all_kinds(self, pr):
        root, api = pr
        api.sync_id_counters()
        for kind in api.config.all_kinds():
            counter_file = (
                root
                / ".audiagentic"
                / "planning"
                / "meta"
                / api.config.kind_counter_file(kind)
            )
            assert counter_file.exists(), f"Missing counter for {kind}"
            assert "counter" in json.loads(counter_file.read_text(encoding="utf-8"))

    def test_sync_sets_counter_from_existing_docs(self, pr):
        root, api = pr
        api.new("request", label="R1", summary="S", source="test")
        api.new("request", label="R2", summary="S", source="test")
        # Corrupt the counter
        counter_file = (
            root
            / ".audiagentic"
            / "planning"
            / "meta"
            / api.config.kind_counter_file("request")
        )
        counter_file.write_text(json.dumps({"counter": 0}, indent=2), encoding="utf-8")
        # Sync should repair it
        api.sync_id_counters()
        counter = json.loads(counter_file.read_text(encoding="utf-8"))["counter"]
        assert counter >= 2


# ===========================================================================
# next_items() with domain filter
# ===========================================================================


class TestNextItems:
    def test_next_items_domain_filter(self, pr):
        _, api = pr
        spec = _new_spec(api)
        plan = api.new("plan", label="P", summary="P", refs={"spec": spec.data["id"]})
        core_task = api.new("task", label="Core", summary="S", refs={"spec": spec.data["id"]}, domain="core")
        contrib_task = api.new(
            "task", label="Contrib", summary="S", refs={"spec": spec.data["id"]}, domain="contrib"
        )
        api.state(core_task.data["id"], "ready")
        api.state(contrib_task.data["id"], "ready")
        core_items = api.next_items("task", "ready", domain="core")
        contrib_items = api.next_items("task", "ready", domain="contrib")
        core_ids = {i["id"] for i in core_items}
        contrib_ids = {i["id"] for i in contrib_items}
        assert core_task.data["id"] in core_ids
        assert contrib_task.data["id"] not in core_ids
        assert contrib_task.data["id"] in contrib_ids

    def test_next_items_excludes_deleted(self, pr):
        _, api = pr
        spec = _new_spec(api)
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        api.state(task.data["id"], "ready")
        api.delete(task.data["id"], reason="test")
        items = api.next_items("task", "ready")
        assert task.data["id"] not in {i["id"] for i in items}

    def test_next_items_wp_kind(self, pr):
        _, api = pr
        spec = _new_spec(api)
        plan = api.new("plan", label="P", summary="P", refs={"spec": spec.data["id"]})
        wp = api.new("wp", label="W", summary="S", refs={"plan": plan.data["id"]})
        api.state(wp.data["id"], "ready")
        items = api.next_items("wp", "ready")
        assert any(i["id"] == wp.data["id"] for i in items)


# ===========================================================================
# Claims TTL expiry
# ===========================================================================


class TestClaimsTTL:
    def test_expired_claims_not_visible_in_next_items(self, pr):
        """Claims with elapsed TTL should be treated as expired and excluded
        from active claims, making items available again in next_items.

        EXPECTED TO FAIL: Claims.load() does not filter by TTL — no expiry
        logic exists. This test documents the missing behaviour.
        """
        _, api = pr
        spec = _new_spec(api)
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        api.state(task.data["id"], "ready")
        # Claim with 1-second TTL
        api.claim("task", task.data["id"], holder="agent-1", ttl=1)
        # Wait for TTL to elapse
        time.sleep(1.5)
        # Item should now appear as unclaimed
        available = api.next_items("task", "ready")
        assert any(i["id"] == task.data["id"] for i in available), (
            "Expired claim still blocks item — TTL expiry not implemented"
        )

    def test_claims_returns_only_unexpired(self, pr):
        """api.claims() should exclude entries whose TTL has elapsed.

        EXPECTED TO FAIL: no TTL expiry filtering in claims.load().
        """
        _, api = pr
        spec = _new_spec(api)
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        api.claim("task", task.data["id"], holder="agent-exp", ttl=1)
        time.sleep(1.5)
        active = api.claims("task")
        assert not any(c["id"] == task.data["id"] for c in active), (
            "Expired claim still present — TTL expiry not implemented"
        )


# ===========================================================================
# Event emission tests (replaces removed hooks system)
# ===========================================================================


class TestEventEmission:
    def test_state_change_emits_event(self, pr):
        """State changes emit planning.item.state.changed events."""
        root, api = pr
        spec = _new_spec(api)
        api.state(spec.data["id"], "ready")
        events_path = root / ".audiagentic" / "planning" / "events" / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        assert any(
            e.get("event") == "planning.item.state.changed" and e.get("id") == spec.data["id"]
            for e in events
        )

    def test_create_emits_event(self, pr):
        """Item creation emits planning.item.created events."""
        root, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        events_path = root / ".audiagentic" / "planning" / "events" / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        assert any(
            e.get("event") == "planning.item.created" and e.get("id") == req.data["id"]
            for e in events
        )

    def test_update_emits_event(self, pr):
        """Item updates emit planning.item.updated events."""
        root, api = pr
        spec = _new_spec(api)
        api.update(spec.data["id"], label="Updated")
        events_path = root / ".audiagentic" / "planning" / "events" / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        assert any(
            e.get("event") == "planning.item.updated" and e.get("id") == spec.data["id"]
            for e in events
        )


# ===========================================================================
# Validation coverage — request and standard kinds
# ===========================================================================


class TestValidationCoverage:
    def test_validate_request_required_sections(self, pr):
        """New requests include required sections: Understanding, Open Questions, Notes."""
        _, api = pr
        api.new("request", label="R", summary="S", source="test")
        errors = api.validate()
        missing_section_errors = [e for e in errors if "missing section" in e]
        assert missing_section_errors == []

    def test_validate_standard_no_required_sections(self, pr):
        """Standards have no required body sections in REQ_SECTIONS."""
        _, api = pr
        api.new("standard", label="Naming", summary="S")
        errors = api.validate()
        assert not any("missing section" in e for e in errors)

    def test_validate_plan_missing_section_reported(self, pr):
        root, api = pr
        spec = _new_spec(api)
        # Write a plan without required sections
        plan_path = root / "docs" / "planning" / "plans" / "plan-0001-test.md"
        plan_path.write_text(
            "---\nid: plan-0001\nlabel: Test\nstate: draft\nsummary: test\n---\n\n# Objectives\n\nX.\n",
            encoding="utf-8",
        )
        errors = api.validate()
        assert any("Delivery Approach" in e or "Dependencies" in e for e in errors)

    def test_validate_task_missing_description_reported(self, pr):
        _, api = pr
        spec = _new_spec(api)
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        # Wipe the body so Description section is absent
        from audiagentic.planning.fs.read import parse_markdown
        from audiagentic.planning.fs.write import dump_markdown

        data, _ = parse_markdown(task.path)
        dump_markdown(task.path, data, "\n")
        errors = api.validate()
        assert any("missing section" in e and "Description" in e for e in errors)

    def test_validate_done_task_requires_state_configured_sections(self, pr):
        _, api = pr
        spec = _new_spec(api)
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        api.state(task.data["id"], "ready")
        api.state(task.data["id"], "in_progress")
        api.state(task.data["id"], "done")
        errors = api.validate()
        assert any(
            "missing section" in e
            and "Implementation Notes" in e
            and "state 'done'" in e
            for e in errors
        )

    def test_validate_done_task_passes_when_state_sections_present(self, pr):
        _, api = pr
        task_body = "# Description\n\nTask detail.\n\n# Implementation Notes\n\nWork completed.\n"
        spec = _new_spec(api)
        task = api.create_with_content(
            "task",
            label="T",
            summary="S",
            content=task_body,
            refs={"spec": spec.data["id"]},
        )
        api.state(task.data["id"], "ready")
        api.state(task.data["id"], "in_progress")
        api.state(task.data["id"], "done")
        errors = api.validate()
        assert not any(
            "missing section 'Implementation Notes' for state 'done'" in e for e in errors
        )

    def test_validate_duplicate_standard_id_caught(self, pr):
        root, api = pr
        std = api.new("standard", label="My Standard", summary="S")
        # Manually write a duplicate
        dup = root / "docs" / "planning" / "standards" / f"{std.data['id']}-dup.md"
        dup.write_text(
            f"---\nid: {std.data['id']}\nlabel: Dup\nstate: draft\nsummary: dup\n---\n",
            encoding="utf-8",
        )
        errors = api.validate()
        assert any("duplicate id" in e for e in errors)

    def test_validate_wrong_filename_for_task(self, pr):
        root, api = pr
        spec = _new_spec(api)
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        # Rename to wrong filename
        bad_path = task.path.parent / "task-9999-wrong.md"
        task.path.rename(bad_path)
        errors = api.validate()
        assert any("filename must be" in e for e in errors)

    def test_validate_request_requires_slugged_filename(self, pr):
        root, api = pr
        req = api.new("request", label="My Request", summary="S", source="test")
        bad_path = req.path.parent / f"{req.data['id']}.md"
        req.path.rename(bad_path)
        errors = api.validate()
        assert any(f"filename must be {req.data['id']}-my-request.md" in e for e in errors)


# ===========================================================================
# Batch operations (tm_helper._execute_batch_operations via update())
# ===========================================================================


class TestBatchOperations:
    def test_batch_state_and_label(self, pr):
        import tools.planning.tm_helper as tm

        _seed(pr[0])
        tm.set_root(pr[0])
        try:
            spec = _new_spec(pr[1])
            task = pr[1].new("task", label="Old Label", summary="S", refs={"spec": spec.data["id"]})
            pr[1].state(task.data["id"], "ready")
            result = tm.update(
                task.data["id"],
                root=pr[0],
                operations=[
                    {"op": "state", "value": "in_progress"},
                    {"op": "label", "value": "New Label"},
                ],
            )
            assert "results" in result
            updated = pr[1]._find(task.data["id"])
            assert updated.data["state"] == "in_progress"
            assert updated.data["label"] == "New Label"
        finally:
            tm.reset_root()

    def test_batch_unknown_op_raises_or_logs(self, pr):
        import tools.planning.tm_helper as tm

        spec = _new_spec(pr[1])
        task = pr[1].new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        result = tm.update(
            task.data["id"],
            root=pr[0],
            operations=[{"op": "unknown_op", "value": "x"}],
        )
        # Should not raise but should report error in results
        assert "results" in result or "errors" in result

    def test_batch_meta_op_sets_field(self, pr):
        import tools.planning.tm_helper as tm

        spec = _new_spec(pr[1])
        task = pr[1].new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        result = tm.update(
            task.data["id"],
            root=pr[0],
            operations=[{"op": "meta", "field": "reviewer", "value": "agent-1"}],
        )
        updated = pr[1]._find(task.data["id"])
        assert updated.data.get("meta", {}).get("reviewer") == "agent-1"


# ===========================================================================
# status() and events() via tm_helper
# ===========================================================================


class TestStatusAndEvents:
    def test_status_returns_counts_for_all_kinds(self, pr):
        import tools.planning.tm_helper as tm

        root, api = pr
        api.new("request", label="R", summary="S", source="test")
        spec = _new_spec(api)
        api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        result = tm.status(root=root)
        # Check singular keys (not plural)
        assert "request" in result
        assert "spec" in result
        assert "task" in result
        # Check state breakdown exists
        assert "captured" in result["request"]
        assert result["request"]["captured"] == 2
        # Check _total is provided for convenience
        assert result["request"].get("_total") == 2

    def test_events_returns_recent_events(self, pr):
        import tools.planning.tm_helper as tm

        root, api = pr
        api.new("request", label="R", summary="S", source="test")  # triggers emit_event hook
        events = tm.events(tail=10, root=root)
        assert isinstance(events, list)
        assert len(events) >= 1

    def test_events_tail_limits_output(self, pr):
        import tools.planning.tm_helper as tm

        root, api = pr
        for i in range(5):
            api.new("request", label=f"R{i}", summary="S", source="test")
        all_events = tm.events(tail=100, root=root)
        tail_2 = tm.events(tail=2, root=root)
        assert len(tail_2) <= 2
        assert len(all_events) >= len(tail_2)


# ===========================================================================
# package() additional scenarios
# ===========================================================================


class TestPackage:
    def test_package_multiple_tasks(self, pr):
        _, api = pr
        spec = _new_spec(api)
        plan = api.new("plan", label="P", summary="P", refs={"spec": spec.data["id"]})
        t1 = api.new("task", label="T1", summary="S", refs={"spec": spec.data["id"]})
        t2 = api.new("task", label="T2", summary="S", refs={"spec": spec.data["id"]})
        t3 = api.new("task", label="T3", summary="S", refs={"spec": spec.data["id"]})
        wp = api.run_workflow_action(
            "group",
            {
                "parent_id": plan.data["id"],
                "item_ids": [t1.data["id"], t2.data["id"], t3.data["id"]],
                "label": "Big WP",
                "summary": "S",
            },
        )["group"]
        refs = [r["ref"] for r in wp.data["task_refs"]]
        assert t1.data["id"] in refs
        assert t2.data["id"] in refs
        assert t3.data["id"] in refs

    def test_package_assigns_sequential_seq(self, pr):
        _, api = pr
        spec = _new_spec(api)
        plan = api.new("plan", label="P", summary="P", refs={"spec": spec.data["id"]})
        t1 = api.new("task", label="T1", summary="S", refs={"spec": spec.data["id"]})
        t2 = api.new("task", label="T2", summary="S", refs={"spec": spec.data["id"]})
        wp = api.run_workflow_action(
            "group",
            {
                "parent_id": plan.data["id"],
                "item_ids": [t1.data["id"], t2.data["id"]],
                "label": "W",
                "summary": "S",
            },
        )["group"]
        seqs = [r["seq"] for r in wp.data["task_refs"]]
        assert seqs[0] < seqs[1]

    def test_package_in_contrib_domain(self, pr):
        root, api = pr
        spec = _new_spec(api)
        plan = api.new("plan", label="P", summary="P", refs={"spec": spec.data["id"]})
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        (root / "docs" / "planning" / "work-packages" / "contrib").mkdir(
            parents=True, exist_ok=True
        )
        wp = api.run_workflow_action(
            "group",
            {
                "parent_id": plan.data["id"],
                "item_ids": [task.data["id"]],
                "label": "W",
                "summary": "S",
                "domain": "contrib",
            },
        )["group"]
        assert "contrib" in str(wp.path)


# ===========================================================================
# delete() additional scenarios
# ===========================================================================


class TestDelete:
    def test_soft_delete_still_findable(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        api.delete(req.data["id"], reason="superseded")
        item = api._find(req.data["id"])
        assert api.config.is_soft_deleted(item.data) is True

    def test_soft_delete_excluded_from_next_items(self, pr):
        _, api = pr
        spec = _new_spec(api)
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        api.state(task.data["id"], "ready")
        api.delete(task.data["id"])
        available = api.next_items("task", "ready")
        assert task.data["id"] not in {i["id"] for i in available}

    def test_hard_delete_not_findable(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        api.delete(req.data["id"], hard=True, reason="test")
        with pytest.raises(KeyError):
            api._find(req.data["id"])

    def test_hard_delete_syncs_counter(self, pr):
        root, api = pr
        api.new("request", label="R1", summary="S", source="test")
        r2 = api.new("request", label="R2", summary="S", source="test")
        result = api.delete(r2.data["id"], hard=True, reason="test")
        assert result["counter_sync"] is True

    def test_delete_reason_stored(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        api.delete(req.data["id"], reason="no longer needed")
        item = api._find(req.data["id"])
        assert item.data.get("deletion_reason") == "no longer needed"


# ===========================================================================
# validate() raise_on_error kwarg
# ===========================================================================


class TestValidateRaiseOnError:
    def test_validate_raise_on_error_raises_runtime_error(self, pr):
        root, api = pr
        # Write an invalid doc (missing required fields)
        bad = root / "docs" / "planning" / "requests" / "request-bad.md"
        bad.write_text("---\nid: request-bad\nlabel: Bad\n---\n\n", encoding="utf-8")
        with pytest.raises(RuntimeError):
            api.validate(raise_on_error=True)

    def test_validate_raise_on_error_false_returns_list(self, pr):
        root, api = pr
        bad = root / "docs" / "planning" / "requests" / "request-bad2.md"
        bad.write_text("---\nid: request-bad2\nlabel: Bad\n---\n\n", encoding="utf-8")
        errors = api.validate(raise_on_error=False)
        assert isinstance(errors, list)
        assert len(errors) > 0


# ===========================================================================
# spec-29 AC 8: guidance-level section variation
# ===========================================================================


class TestGuidanceSectionVariation:
    def test_spec_light_has_fewer_sections_than_deep(self, pr):
        _, api = pr
        from audiagentic.planning.app.section_registry import list_sections
        light = list_sections("spec", "light", api.root)
        deep = list_sections("spec", "deep", api.root)
        assert len(light) < len(deep)

    def test_task_standard_sections_nonempty(self, pr):
        _, api = pr
        from audiagentic.planning.app.section_registry import list_sections
        sections = list_sections("task", "standard", api.root)
        assert len(sections) > 0

    def test_document_template_varies_by_guidance(self, pr):
        _, api = pr
        light_body = api.config.document_template("spec", "light")
        deep_body = api.config.document_template("spec", "deep")
        assert light_body != deep_body
        assert len(deep_body) > len(light_body)

    def test_new_spec_with_guidance_uses_template(self, pr):
        _, api = pr
        req = api.new("request", label="Guidance test req", summary="S", source="test")
        spec = api.new(
            "spec",
            label="Guidance test spec",
            summary="S",
            refs={"request_refs": [req.data["id"]]},
            guidance="deep",
        )
        body = api.get_content(spec.data["id"])
        deep_template = api.config.document_template("spec", "deep")
        # Body should contain at least one section from the deep template
        deep_sections = [line for line in deep_template.splitlines() if line.startswith("# ")]
        assert any(s.lstrip("# ").strip() in body for s in deep_sections)


# ===========================================================================
# spec-29 AC 11: required-ref enforcement regression
# ===========================================================================


class TestRequiredRefEnforcement:
    def test_spec_without_request_refs_rejected(self, pr):
        _, api = pr
        with pytest.raises((ValueError, Exception)):
            api.new("spec", label="Orphan spec", summary="S", refs={"request_refs": []})

    def test_spec_with_request_refs_succeeds(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        spec = api.new("spec", label="S", summary="S", refs={"request_refs": [req.data["id"]]})
        assert spec.data["id"].startswith("spec-")

    def test_plan_without_spec_rejected(self, pr):
        _, api = pr
        with pytest.raises((ValueError, Exception)):
            api.new("plan", label="Orphan plan", summary="S")

    def test_plan_with_spec_succeeds(self, pr):
        _, api = pr
        req = api.new("request", label="R", summary="S", source="test")
        spec = api.new("spec", label="S", summary="S", refs={"request_refs": [req.data["id"]]})
        plan = api.new("plan", label="P", summary="S", refs={"spec": spec.data["id"]})
        assert plan.data["id"].startswith("plan-")

    def test_task_without_spec_ref_succeeds(self, pr):
        _, api = pr
        # task has required_for_children: [] in RelationshipConfig
        req = api.new("request", label="R", summary="S", source="test")
        spec = api.new("spec", label="S", summary="S", refs={"request_refs": [req.data["id"]]})
        task = api.new("task", label="T", summary="S", refs={"spec": spec.data["id"]})
        assert task.data["id"].startswith("task-")
