"""Unit tests for foundation/workflow/propagation/parents.py and util.extract_ref_ids."""

from __future__ import annotations

from audiagentic.foundation.workflow.propagation.parents import (
    find_parents,
    linked_child_ids,
)
from audiagentic.foundation.workflow.util import extract_ref_ids

from .conftest import FakeContext

# ── extract_ref_ids ───────────────────────────────────────────────────────────

def test_extract_none() -> None:
    assert extract_ref_ids(None) == []


def test_extract_string() -> None:
    assert extract_ref_ids("task-1") == ["task-1"]


def test_extract_dict_with_ref() -> None:
    assert extract_ref_ids({"ref": "task-1", "seq": 1000}) == ["task-1"]


def test_extract_dict_without_ref() -> None:
    assert extract_ref_ids({"display": "Task 1"}) == []


def test_extract_dict_ref_not_string() -> None:
    assert extract_ref_ids({"ref": 42}) == []


def test_extract_list_of_strings() -> None:
    assert extract_ref_ids(["task-1", "task-2"]) == ["task-1", "task-2"]


def test_extract_list_of_dicts() -> None:
    refs = [{"ref": "task-1"}, {"ref": "task-2"}]
    assert extract_ref_ids(refs) == ["task-1", "task-2"]


def test_extract_mixed_list() -> None:
    refs = ["task-1", {"ref": "task-2"}, {"display": "no ref"}]
    assert extract_ref_ids(refs) == ["task-1", "task-2"]


def test_extract_nested_list() -> None:
    assert extract_ref_ids([["task-1", "task-2"]]) == ["task-1", "task-2"]


def test_extract_empty_list() -> None:
    assert extract_ref_ids([]) == []


def test_extract_unknown_type() -> None:
    assert extract_ref_ids(42) == []


# ── find_parents ──────────────────────────────────────────────────────────────

def test_find_parents_no_parent_kind() -> None:
    ctx = FakeContext()
    ctx.add_item("c-1", "task", state="draft")
    assert find_parents(ctx, "c-1", None, "parent_ref") == []


def test_find_parents_no_parent_field() -> None:
    ctx = FakeContext()
    ctx.add_item("c-1", "task", state="draft")
    assert find_parents(ctx, "c-1", "plan", None) == []


def test_find_parents_item_not_found() -> None:
    ctx = FakeContext()
    assert find_parents(ctx, "missing", "plan", "plan_ref") == []


def test_find_parents_direct_scalar_ref() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active")
    ctx.add_item("c-1", "task", state="draft", plan_ref="p-1")
    result = find_parents(ctx, "c-1", "plan", "plan_ref")
    assert result == [("p-1", "plan")]


def test_find_parents_direct_list_ref() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active")
    ctx.add_item("c-1", "task", state="draft", parent_refs=["p-1"])
    result = find_parents(ctx, "c-1", "plan", "parent_refs")
    assert result == [("p-1", "plan")]


def test_find_parents_reverse_lookup_when_no_direct_ref() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", child_refs=["c-1"])
    ctx.add_item("c-1", "task", state="draft")
    result = find_parents(ctx, "c-1", "plan", "child_refs")
    assert result == [("p-1", "plan")]


def test_find_parents_reverse_returns_only_correct_kind() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", child_refs=["c-1"])
    ctx.add_item("x-1", "spec", state="active", child_refs=["c-1"])
    ctx.add_item("c-1", "task", state="draft")
    result = find_parents(ctx, "c-1", "plan", "child_refs")
    parent_ids = {pid for pid, _ in result}
    assert "p-1" in parent_ids
    assert "x-1" not in parent_ids


def test_find_parents_prefers_direct_over_reverse() -> None:
    ctx = FakeContext()
    ctx.add_item("p-direct", "plan", state="active")
    ctx.add_item("p-reverse", "plan", state="active", child_refs=["c-1"])
    ctx.add_item("c-1", "task", state="draft", plan_ref="p-direct")
    result = find_parents(ctx, "c-1", "plan", "plan_ref")
    assert result == [("p-direct", "plan")]


# ── linked_child_ids ──────────────────────────────────────────────────────────

def test_linked_child_ids_via_parent_list() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=[{"ref": "t-1"}, {"ref": "t-2"}])
    ctx.add_item("t-1", "task", state="draft")
    ctx.add_item("t-2", "task", state="draft")
    result = linked_child_ids(ctx, "p-1", "plan", "task", "task_refs")
    assert set(result) == {"t-1", "t-2"}


def test_linked_child_ids_via_reverse_ref() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active")
    ctx.add_item("t-1", "task", state="draft", plan_ref="p-1")
    ctx.add_item("t-2", "task", state="draft", plan_ref="p-1")
    result = linked_child_ids(ctx, "p-1", "plan", "task", "plan_ref")
    assert set(result) == {"t-1", "t-2"}


def test_linked_child_ids_no_duplicates() -> None:
    """Child listed in parent.task_refs AND child.plan_ref pointing back — no dup."""
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="draft", task_refs="p-1")
    result = linked_child_ids(ctx, "p-1", "plan", "task", "task_refs")
    assert result.count("t-1") == 1


def test_linked_child_ids_excludes_wrong_kind() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1", "s-1"])
    ctx.add_item("t-1", "task", state="draft")
    ctx.add_item("s-1", "spec", state="draft")
    result = linked_child_ids(ctx, "p-1", "plan", "task", "task_refs")
    assert "t-1" in result
    assert "s-1" not in result


def test_linked_child_ids_skips_missing_items() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1", "ghost"])
    ctx.add_item("t-1", "task", state="draft")
    result = linked_child_ids(ctx, "p-1", "plan", "task", "task_refs")
    assert "t-1" in result
    assert "ghost" not in result
