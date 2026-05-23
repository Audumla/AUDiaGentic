"""Unit tests for FrontmatterBuilder, Relationships, and util functions."""

from __future__ import annotations

from audiagentic.foundation.workflow import Relationships
from audiagentic.foundation.workflow.frontmatter import FrontmatterBuilder
from audiagentic.foundation.workflow.util import body_has_section, now_iso, slugify

from .conftest import FakeConfig

# ── slugify ───────────────────────────────────────────────────────────────────

def test_slugify_lowercases() -> None:
    assert slugify("Hello World") == "hello-world"


def test_slugify_replaces_special_chars_with_hyphen() -> None:
    assert slugify("foo/bar baz") == "foo-bar-baz"


def test_slugify_collapses_multiple_hyphens() -> None:
    assert slugify("a---b") == "a-b"


def test_slugify_strips_leading_trailing_hyphens() -> None:
    assert slugify("--hello--") == "hello"


def test_slugify_empty_returns_item() -> None:
    assert slugify("") == "item"


def test_slugify_all_special_returns_item() -> None:
    assert slugify("!!!") == "item"


def test_slugify_preserves_numbers() -> None:
    assert slugify("Task 42") == "task-42"


# ── now_iso ───────────────────────────────────────────────────────────────────

def test_now_iso_is_string() -> None:
    ts = now_iso()
    assert isinstance(ts, str)


def test_now_iso_contains_t_separator() -> None:
    assert "T" in now_iso()


def test_now_iso_ends_with_utc_offset() -> None:
    ts = now_iso()
    assert ts.endswith("+00:00") or ts.endswith("Z")


# ── body_has_section ──────────────────────────────────────────────────────────

def test_body_has_section_h1() -> None:
    assert body_has_section("# Background\nsome text", "Background") is True


def test_body_has_section_h2() -> None:
    assert body_has_section("## Notes\ntext", "Notes") is True


def test_body_has_section_absent() -> None:
    assert body_has_section("# Something Else\n", "Notes") is False


def test_body_has_section_case_sensitive() -> None:
    assert body_has_section("# notes\n", "Notes") is False


def test_body_has_section_substring_matches() -> None:
    # body_has_section checks substring — "# Notes" is present in "# Notesworthy"
    assert body_has_section("# Notesworthy\n", "Notes") is True


# ── Relationships.ensure_rel_list ─────────────────────────────────────────────

def test_ensure_rel_list_adds_to_empty() -> None:
    result = Relationships.ensure_rel_list([], "task-1", seq=1000)
    assert len(result) == 1
    assert result[0]["ref"] == "task-1"
    assert result[0]["seq"] == 1000


def test_ensure_rel_list_updates_existing_ref() -> None:
    current = [{"ref": "task-1", "seq": 1000}]
    result = Relationships.ensure_rel_list(current, "task-1", seq=2000, display="Updated")
    assert len(result) == 1
    assert result[0]["seq"] == 2000
    assert result[0]["display"] == "Updated"


def test_ensure_rel_list_no_duplicate_on_update() -> None:
    current = [{"ref": "task-1", "seq": 1000}, {"ref": "task-2", "seq": 2000}]
    result = Relationships.ensure_rel_list(current, "task-1", seq=500)
    assert len(result) == 2


def test_ensure_rel_list_sorted_by_seq() -> None:
    current = [{"ref": "task-1", "seq": 3000}, {"ref": "task-2", "seq": 1000}]
    result = Relationships.ensure_rel_list(current, "task-3", seq=2000)
    seqs = [r["seq"] for r in result]
    assert seqs == sorted(seqs)


def test_ensure_rel_list_equal_seq_sorted_by_ref() -> None:
    current = [{"ref": "z-1", "seq": 1000}, {"ref": "a-1", "seq": 1000}]
    result = Relationships.ensure_rel_list(current, "m-1", seq=1000)
    refs = [r["ref"] for r in result if r.get("seq") == 1000]
    assert refs == sorted(refs)


def test_ensure_rel_list_none_seq_omitted() -> None:
    result = Relationships.ensure_rel_list([], "task-1")
    assert "seq" not in result[0]


def test_ensure_rel_list_none_display_omitted() -> None:
    result = Relationships.ensure_rel_list([], "task-1", seq=1000)
    assert "display" not in result[0]


def test_ensure_rel_list_none_current_treated_as_empty() -> None:
    result = Relationships.ensure_rel_list(None, "task-1", seq=1000)
    assert len(result) == 1


# ── FrontmatterBuilder ────────────────────────────────────────────────────────

def _builder() -> FrontmatterBuilder:
    return FrontmatterBuilder(FakeConfig())


def test_build_sets_required_fields() -> None:
    fm = _builder().build(
        kind="task", id_="t-1", label="Test", summary="A task",
        domain=None, workflow=None, refs=None, fields=None,
        profile=None, guidance=None, current_understanding=None,
        open_questions=None, source=None, context=None,
    )
    assert fm["id"] == "t-1"
    assert fm["label"] == "Test"
    assert fm["summary"] == "A task"
    assert fm["state"] == "draft"


def test_build_domain_omitted_when_none() -> None:
    fm = _builder().build(
        kind="task", id_="t-1", label="L", summary="S",
        domain=None, workflow=None, refs=None, fields=None,
        profile=None, guidance=None, current_understanding=None,
        open_questions=None, source=None, context=None,
    )
    assert "domain" not in fm


def test_build_domain_included_when_provided() -> None:
    fm = _builder().build(
        kind="task", id_="t-1", label="L", summary="S",
        domain="core", workflow=None, refs=None, fields=None,
        profile=None, guidance=None, current_understanding=None,
        open_questions=None, source=None, context=None,
    )
    assert fm["domain"] == "core"


def test_build_workflow_set_when_provided() -> None:
    fm = _builder().build(
        kind="task", id_="t-1", label="L", summary="S",
        domain=None, workflow="custom", refs=None, fields=None,
        profile=None, guidance=None, current_understanding=None,
        open_questions=None, source=None, context=None,
    )
    assert fm["workflow"] == "custom"


def test_build_uses_provided_state() -> None:
    fm = _builder().build(
        kind="task", id_="t-1", label="L", summary="S",
        domain=None, workflow=None, refs=None, fields=None,
        profile=None, guidance=None, current_understanding=None,
        open_questions=None, source=None, context=None, state="active",
    )
    assert fm["state"] == "active"


def test_build_fields_override_wins() -> None:
    fm = _builder().build(
        kind="task", id_="t-1", label="L", summary="S",
        domain=None, workflow=None, refs=None,
        fields={"summary": "Override"},
        profile=None, guidance=None, current_understanding=None,
        open_questions=None, source=None, context=None,
    )
    assert fm["summary"] == "Override"


def test_build_empty_fields_not_included() -> None:
    fm = _builder().build(
        kind="task", id_="t-1", label="L", summary="S",
        domain=None, workflow=None, refs=None,
        fields={"empty_field": None, "empty_list": []},
        profile=None, guidance=None, current_understanding=None,
        open_questions=None, source=None, context=None,
    )
    assert "empty_field" not in fm
    assert "empty_list" not in fm


# ── FrontmatterBuilder._coerce_reference_value ───────────────────────────────

def test_coerce_none_returns_none() -> None:
    b = _builder()
    assert b._coerce_reference_value("x", None) is None


def test_coerce_scalar_ref_list_from_string() -> None:
    cfg = FakeConfig()
    cfg.reference_field_shape = lambda f: "scalar_ref_list"
    b = FrontmatterBuilder(cfg)
    assert b._coerce_reference_value("refs", "task-1") == ["task-1"]


def test_coerce_scalar_ref_from_single_element_list() -> None:
    cfg = FakeConfig()
    cfg.reference_field_shape = lambda f: "scalar_ref"
    b = FrontmatterBuilder(cfg)
    assert b._coerce_reference_value("ref", ["task-1"]) == "task-1"


def test_coerce_scalar_ref_from_multi_element_list_returns_none() -> None:
    cfg = FakeConfig()
    cfg.reference_field_shape = lambda f: "scalar_ref"
    b = FrontmatterBuilder(cfg)
    assert b._coerce_reference_value("ref", ["t-1", "t-2"]) is None


def test_coerce_rel_list_from_string_list() -> None:
    cfg = FakeConfig()
    cfg.reference_field_shape = lambda f: "rel_list"
    b = FrontmatterBuilder(cfg)
    result = b._coerce_reference_value("refs", ["task-1", "task-2"])
    assert result == [
        {"ref": "task-1", "seq": 1000},
        {"ref": "task-2", "seq": 2000},
    ]


def test_coerce_rel_list_already_structured_unchanged() -> None:
    cfg = FakeConfig()
    cfg.reference_field_shape = lambda f: "rel_list"
    b = FrontmatterBuilder(cfg)
    structured = [{"ref": "task-1", "seq": 500}]
    result = b._coerce_reference_value("refs", structured)
    assert result == structured
