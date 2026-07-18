from __future__ import annotations

from audiagentic.components.providers.prompt_tags import parse_tagged_prompt


def test_parse_tagged_prompt_reads_only_first_non_empty_line() -> None:
    parsed = parse_tagged_prompt("\n  @ag-implement provider=gemini id=PKT-1\nDo the work.\n@ignored")

    assert parsed is not None
    assert parsed.tag == "@ag-implement"
    assert parsed.directives == {"provider": "gemini", "id": "PKT-1"}
    assert parsed.body == "Do the work.\n@ignored"


def test_parse_tagged_prompt_does_not_search_later_lines() -> None:
    assert parse_tagged_prompt("Normal request\n@ag-implement\nDo work") is None
