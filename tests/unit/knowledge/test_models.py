"""Unit tests for knowledge component models."""

from __future__ import annotations

from pathlib import Path

from audiagentic.knowledge.models import (
    DriftItem,
    EventRecord,
    KnowledgePage,
    SearchResult,
    Section,
)


def test_section_holds_title_and_body():
    s = Section(title="Summary", body="Some content here.")
    assert s.title == "Summary"
    assert s.body == "Some content here."


def test_knowledge_page_properties(tmp_path: Path):
    content_path = tmp_path / "pages" / "guides" / "my-guide.md"
    meta_path = tmp_path / "meta" / "guides" / "my-guide.meta.yml"
    content_path.parent.mkdir(parents=True)
    meta_path.parent.mkdir(parents=True)
    content_path.write_text("## Summary\n\nContent.\n", encoding="utf-8")
    meta_path.write_text("id: my-guide\ntitle: My Guide\n", encoding="utf-8")

    page = KnowledgePage(
        content_path=content_path,
        meta_path=meta_path,
        metadata={"id": "my-guide", "title": "My Guide", "type": "guide", "tags": ["alpha", "beta"]},
        sections=[Section(title="Summary", body="Content.")],
        raw_body="## Summary\n\nContent.\n",
    )

    assert page.page_id == "my-guide"
    assert page.title == "My Guide"
    assert page.page_type == "guide"
    assert page.tags == ["alpha", "beta"]


def test_knowledge_page_tags_default_empty(tmp_path: Path):
    content_path = tmp_path / "page.md"
    meta_path = tmp_path / "page.meta.yml"
    content_path.write_text("", encoding="utf-8")
    meta_path.write_text("id: x\n", encoding="utf-8")

    page = KnowledgePage(
        content_path=content_path,
        meta_path=meta_path,
        metadata={"id": "x"},
        sections=[],
        raw_body="",
    )
    assert page.tags == []


def test_knowledge_page_section_map(tmp_path: Path):
    content_path = tmp_path / "page.md"
    meta_path = tmp_path / "page.meta.yml"
    content_path.write_text("", encoding="utf-8")
    meta_path.write_text("id: x\n", encoding="utf-8")

    sections = [Section("Overview", "body1"), Section("Details", "body2")]
    page = KnowledgePage(
        content_path=content_path,
        meta_path=meta_path,
        metadata={"id": "x"},
        sections=sections,
        raw_body="",
    )
    smap = page.section_map
    assert "Overview" in smap
    assert smap["Overview"].body == "body1"
    assert "Details" in smap


def test_search_result_fields():
    r = SearchResult(
        path="docs/pages/guide.md",
        page_id="guide",
        title="My Guide",
        score=3.5,
        snippet="some text...",
        matches=["title:1", "body:2"],
    )
    assert r.page_id == "guide"
    assert r.score == 3.5
    assert "title:1" in r.matches


def test_drift_item_fields():
    d = DriftItem(
        page_id="my-guide",
        title="My Guide",
        source_path="docs/pages/guide.md",
        status="changed",
        message="content changed",
        fingerprint_before="abc",
        fingerprint_now="def",
        diff_excerpt="- old\n+ new",
        details={"changed_keys": ["summary"]},
    )
    assert d.status == "changed"
    assert d.fingerprint_before == "abc"
    assert d.details["changed_keys"] == ["summary"]


def test_event_record_fields():
    e = EventRecord(
        event_id="adapter::path::abc123",
        adapter_id="planning-adapter",
        event_name="planning.item.state.changed",
        source_path=".audiagentic/planning/events.jsonl",
        status="done",
        observed_at="2026-04-17T10:00:00Z",
        affected_pages=["system-planning"],
        fingerprint_before=None,
        fingerprint_now="xyz",
        summary="Task done",
        diff_excerpt=None,
        details={"payload": {}},
    )
    assert e.event_id == "adapter::path::abc123"
    assert e.affected_pages == ["system-planning"]
    assert e.fingerprint_before is None
