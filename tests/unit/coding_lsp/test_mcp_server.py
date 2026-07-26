from __future__ import annotations

from unittest.mock import patch

from audiagentic.components.coding_lsp import lsp_api, lsp_manage_mcp, lsp_mcp


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


def test_lsp_navigate_definition_delegates_to_api() -> None:
    with patch("audiagentic.components.coding_lsp.lsp_api.definition", return_value=[{"ok": True}]) as mock:
        assert lsp_mcp.lsp_navigate("file.py", "1:1", kind="definition") == [{"ok": True}]
        mock.assert_called_once_with("file.py", "1:1")


def test_lsp_navigate_callers_maps_to_incoming_call_hierarchy() -> None:
    with patch(
        "audiagentic.components.coding_lsp.lsp_api.call_hierarchy", return_value=[{"c": 1}],
    ) as mock:
        assert lsp_mcp.lsp_navigate("file.py", "2:3", kind="callers") == [{"c": 1}]
        mock.assert_called_once_with("file.py", "2:3", direction="incoming")


def test_lsp_navigate_unknown_kind_returns_error() -> None:
    out = lsp_mcp.lsp_navigate("file.py", "1:1", kind="bogus")
    assert out and "error" in out[0]


def test_lsp_diagnostics_scopes_by_paths() -> None:
    with patch("audiagentic.components.coding_lsp.lsp_api.diagnostics", return_value={}) as repo, \
         patch("audiagentic.components.coding_lsp.lsp_api.file_diagnostics", return_value=[{"d": 1}]) as one, \
         patch("audiagentic.components.coding_lsp.lsp_api.changed_diagnostics", return_value={}) as many:
        lsp_mcp.lsp_diagnostics()
        repo.assert_called_once()
        assert lsp_mcp.lsp_diagnostics(paths=["a.py"]) == {"a.py": [{"d": 1}]}
        one.assert_called_once()
        lsp_mcp.lsp_diagnostics(paths=["a.py", "b.py"])
        many.assert_called_once()


def test_lsp_edit_rename_requires_position_and_name() -> None:
    assert "error" in lsp_mcp.lsp_edit("file.py", "rename")
    with patch("audiagentic.components.coding_lsp.lsp_api.rename_preview", return_value={"ok": True}) as mock:
        assert lsp_mcp.lsp_edit("file.py", "rename", position="1:1", new_name="x") == {"ok": True}
        mock.assert_called_once_with("file.py", "1:1", "x")


def test_lsp_config_status_delegates_to_api() -> None:
    with patch("audiagentic.components.coding_lsp.lsp_config_api.config_status", return_value={"ok": True}) as mock:
        assert lsp_manage_mcp.lsp_config_status(".") == {"ok": True}
        mock.assert_called_once_with(".")


def test_lsp_list_implementations_delegates_to_api() -> None:
    with patch(
        "audiagentic.components.coding_lsp.lsp_config_api.list_implementations",
        return_value={"active": "ag-lsp"},
    ) as mock:
        assert lsp_manage_mcp.lsp_list_implementations("root") == {"active": "ag-lsp"}
        mock.assert_called_once_with("root")


def test_lsp_select_implementation_delegates_to_api() -> None:
    with patch(
        "audiagentic.components.coding_lsp.lsp_config_api.select_implementation",
        return_value={"ok": True},
    ) as mock:
        assert lsp_manage_mcp.lsp_select_implementation("root", "blackwell-agent-lsp") == {"ok": True}
        mock.assert_called_once_with("root", "blackwell-agent-lsp")


def test_lsp_set_language_option_delegates_to_api() -> None:
    with patch(
        "audiagentic.components.coding_lsp.lsp_config_api.set_language_option",
        return_value={"ok": True},
    ) as mock:
        result = lsp_manage_mcp.lsp_set_language_option(
            "root", "python", "server-settings", {"x": True}
        )
        assert result == {"ok": True}
        mock.assert_called_once_with("root", "python", "server-settings", {"x": True})


def test_lsp_reset_language_option_delegates_to_api() -> None:
    with patch(
        "audiagentic.components.coding_lsp.lsp_config_api.reset_language_option",
        return_value={"ok": True},
    ) as mock:
        assert lsp_manage_mcp.lsp_reset_language_option(
            "root", "python", "server-settings"
        ) == {"ok": True}
        mock.assert_called_once_with("root", "python", "server-settings")
