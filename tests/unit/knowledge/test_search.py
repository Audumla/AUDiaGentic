"""Unit tests for knowledge search functions."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from audiagentic.knowledge.config import load_config
from audiagentic.knowledge.models import KnowledgePage, Section
from audiagentic.knowledge.search import _build_snippet, filter_by_metadata, search_pages

ROOT = Path(__file__).resolve().parents[3]


def _seed_project(root: Path) -> None:
    shutil.copytree(ROOT / ".audiagentic" / "knowledge", root / ".audiagentic" / "knowledge", dirs_exist_ok=True)


def _write_page(root: Path, page_id: str, title: str, page_type: str, tags: list[str], body: str) -> None:
    config_raw = yaml.safe_load((root / ".audiagentic" / "knowledge" / "config" / "config.yml").read_text())
    pages_dir = config_raw.get("pages_dir", "pages")
    meta_dir = config_raw.get("meta_dir", "meta")
    knowledge_root = root / config_raw.get("knowledge_root", "knowledge")
    domain = "guides"

    content_path = knowledge_root / pages_dir / domain / f"{page_id}.md"
    meta_path = knowledge_root / meta_dir / domain / f"{page_id}.meta.yml"
    content_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    content_path.write_text(f"## Summary\n\n{body}\n", encoding="utf-8")
    meta_path.write_text(
        yaml.safe_dump({"id": page_id, "title": title, "type": page_type, "tags": tags}, sort_keys=False),
        encoding="utf-8",
    )


# --- filter_by_metadata tests ---

def _make_page(page_id: str, title: str, page_type: str = "guide", tags: list[str] | None = None) -> KnowledgePage:
    from pathlib import Path
    tags = tags or []
    return KnowledgePage(
        content_path=Path(f"{page_id}.md"),
        meta_path=Path(f"{page_id}.meta.yml"),
        metadata={"id": page_id, "title": title, "type": page_type, "tags": tags},
        sections=[Section("Summary", f"Content for {title}.")],
        raw_body=f"## Summary\n\nContent for {title}.\n",
    )


def test_filter_by_metadata_empty_filters():
    pages = [_make_page("a", "Alpha"), _make_page("b", "Beta")]
    result = filter_by_metadata(pages, {})
    assert len(result) == 2


def test_filter_by_metadata_by_type():
    pages = [_make_page("a", "Alpha", "guide"), _make_page("b", "Beta", "system")]
    result = filter_by_metadata(pages, {"type": "guide"})
    assert len(result) == 1
    assert result[0].page_id == "a"


def test_filter_by_metadata_by_type_list():
    pages = [_make_page("a", "Alpha", "guide"), _make_page("b", "Beta", "system"), _make_page("c", "Gamma", "tool")]
    result = filter_by_metadata(pages, {"type": ["guide", "tool"]})
    assert {p.page_id for p in result} == {"a", "c"}


def test_filter_by_metadata_by_tags():
    pages = [
        _make_page("a", "Alpha", tags=["planning", "core"]),
        _make_page("b", "Beta", tags=["knowledge"]),
    ]
    result = filter_by_metadata(pages, {"tags": "planning"})
    assert len(result) == 1
    assert result[0].page_id == "a"


def test_filter_by_metadata_by_id():
    pages = [_make_page("a", "Alpha"), _make_page("b", "Beta")]
    result = filter_by_metadata(pages, {"id": "b"})
    assert len(result) == 1
    assert result[0].page_id == "b"


def test_filter_by_metadata_by_title_contains():
    pages = [_make_page("a", "Alpha Guide"), _make_page("b", "Beta System")]
    result = filter_by_metadata(pages, {"title": "guide"})
    assert len(result) == 1
    assert result[0].page_id == "a"


def test_filter_by_metadata_no_match():
    pages = [_make_page("a", "Alpha", "guide")]
    result = filter_by_metadata(pages, {"type": "system"})
    assert result == []


# --- search_pages tests ---

def test_search_pages_finds_by_title(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    _write_page(tmp_path, "my-guide", "Knowledge Architecture Guide", "guide", [], "Overview of the knowledge architecture.")
    config = load_config(tmp_path)
    results = search_pages(config, "architecture")
    assert any(r.page_id == "my-guide" for r in results)


def test_search_pages_returns_empty_for_no_match(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    _write_page(tmp_path, "my-guide", "My Guide", "guide", [], "Simple content.")
    config = load_config(tmp_path)
    results = search_pages(config, "xyzzy_totally_not_in_any_page")
    assert results == []


def test_search_pages_scores_title_higher_than_body(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    _write_page(tmp_path, "title-match", "Planning System", "guide", [], "Generic content about nothing specific.")
    _write_page(tmp_path, "body-match", "Unrelated Title", "guide", [], "planning system described in body only.")
    config = load_config(tmp_path)
    results = search_pages(config, "planning system")
    ids = [r.page_id for r in results]
    assert "title-match" in ids
    assert "body-match" in ids
    title_score = next(r.score for r in results if r.page_id == "title-match")
    body_score = next(r.score for r in results if r.page_id == "body-match")
    assert title_score > body_score


def test_search_pages_respects_limit(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    for i in range(5):
        _write_page(tmp_path, f"guide-{i}", f"Planning Guide {i}", "guide", [], "planning content")
    config = load_config(tmp_path)
    results = search_pages(config, "planning", limit=3)
    assert len(results) <= 3


def test_search_pages_empty_query_returns_empty(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = load_config(tmp_path)
    results = search_pages(config, "")
    assert results == []


def test_search_pages_result_has_snippet(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    _write_page(tmp_path, "snip-guide", "Snippet Guide", "guide", [], "This content has a unique token abracadabra.")
    config = load_config(tmp_path)
    results = search_pages(config, "abracadabra")
    assert results
    assert results[0].snippet  # non-empty snippet


# --- _build_snippet tests ---

def test_build_snippet_returns_text_around_token():
    text = "word " * 50 + "target" + " word" * 50
    snippet = _build_snippet(text, ["target"], 80)
    assert "target" in snippet
    assert len(snippet) <= 80 + 50  # generous tolerance


def test_build_snippet_no_token_returns_start():
    text = "hello world foo bar"
    snippet = _build_snippet(text, ["missing"], 20)
    assert isinstance(snippet, str)


def test_build_snippet_empty_text():
    snippet = _build_snippet("", ["token"], 80)
    assert isinstance(snippet, str)


def test_search_pages_fuzzy_matches_typo(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    _write_page(tmp_path, "arch-guide", "Architecture Guide", "guide", [], "This explains the architecture of the system.")
    config = load_config(tmp_path)
    # typo: "architeture" instead of "architecture"
    results = search_pages(config, "architeture")
    page_ids = [r.page_id for r in results]
    assert "arch-guide" in page_ids, f"Expected fuzzy match, got: {page_ids}"
