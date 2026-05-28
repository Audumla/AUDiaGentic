from __future__ import annotations

from audiagentic.components.optional.coding_lsp.mcp_server import _parse_position


def test_parse_position_basic() -> None:
    line, char = _parse_position("15:4")
    assert line == 14  # 1-based to 0-based
    assert char == 3


def test_parse_position_first_line() -> None:
    line, char = _parse_position("1:1")
    assert line == 0
    assert char == 0


def test_parse_position_no_column() -> None:
    line, char = _parse_position("10")
    assert line == 9
    assert char == 0
