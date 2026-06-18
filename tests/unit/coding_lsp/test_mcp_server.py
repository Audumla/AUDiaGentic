from __future__ import annotations

from unittest.mock import patch

from audiagentic.components.optional.coding_lsp import lsp_api, lsp_manage_mcp, lsp_mcp


def test_parse_position_basic() -> None:
    line, char = lsp_api.parse_position("15:4")
    assert line == 14
    assert char == 3


def test_parse_position_first_line() -> None:
    line, char = lsp_api.parse_position("1:1")
    assert line == 0
    assert char == 0


def test_parse_position_no_column() -> None:
    line, char = lsp_api.parse_position("10")
    assert line == 9
    assert char == 0


def test_lsp_definition_delegates_to_api() -> None:
    with patch("audiagentic.components.optional.coding_lsp.lsp_api.definition", return_value=[{"ok": True}]) as mock:
        assert lsp_mcp.lsp_definition("file.py", "1:1") == [{"ok": True}]
        mock.assert_called_once_with("file.py", "1:1")


def test_lsp_config_status_delegates_to_api() -> None:
    with patch("audiagentic.components.optional.coding_lsp.lsp_config_api.config_status", return_value={"ok": True}) as mock:
        assert lsp_manage_mcp.lsp_config_status(".") == {"ok": True}
        mock.assert_called_once_with(".")
