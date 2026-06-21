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


def test_lsp_list_implementations_delegates_to_api() -> None:
    with patch(
        "audiagentic.components.optional.coding_lsp.lsp_config_api.list_implementations",
        return_value={"active": "ag-lsp"},
    ) as mock:
        assert lsp_manage_mcp.lsp_list_implementations("root") == {"active": "ag-lsp"}
        mock.assert_called_once_with("root")


def test_lsp_select_implementation_delegates_to_api() -> None:
    with patch(
        "audiagentic.components.optional.coding_lsp.lsp_config_api.select_implementation",
        return_value={"ok": True},
    ) as mock:
        assert lsp_manage_mcp.lsp_select_implementation("root", "agent-lsp") == {"ok": True}
        mock.assert_called_once_with("root", "agent-lsp")


def test_lsp_set_language_option_delegates_to_api() -> None:
    with patch(
        "audiagentic.components.optional.coding_lsp.lsp_config_api.set_language_option",
        return_value={"ok": True},
    ) as mock:
        result = lsp_manage_mcp.lsp_set_language_option(
            "root", "python", "server-settings", {"x": True}
        )
        assert result == {"ok": True}
        mock.assert_called_once_with("root", "python", "server-settings", {"x": True})


def test_lsp_reset_language_option_delegates_to_api() -> None:
    with patch(
        "audiagentic.components.optional.coding_lsp.lsp_config_api.reset_language_option",
        return_value={"ok": True},
    ) as mock:
        assert lsp_manage_mcp.lsp_reset_language_option(
            "root", "python", "server-settings"
        ) == {"ok": True}
        mock.assert_called_once_with("root", "python", "server-settings")
