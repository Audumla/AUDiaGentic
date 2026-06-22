from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from audiagentic.components.source_control import (
    source_control_api,
    source_control_mcp,
)


def test_get_source_control_status_delegates_to_api() -> None:
    with patch.object(source_control_api, "get_source_control_status", return_value={"ok": True}) as mock:
        assert source_control_mcp.get_source_control_status() == {"ok": True}
        mock.assert_called_once_with()


def test_install_dependencies_delegates_to_api() -> None:
    with patch.object(source_control_api, "install_dependencies", new=AsyncMock(return_value={"ok": True})) as mock:
        assert asyncio.run(source_control_mcp.install_dependencies(["git"])) == {"ok": True}
        mock.assert_awaited_once_with(["git"])


def test_uninstall_dependencies_delegates_to_api() -> None:
    with patch.object(source_control_api, "uninstall_dependencies", new=AsyncMock(return_value={"ok": True})) as mock:
        assert asyncio.run(source_control_mcp.uninstall_dependencies(["gh"])) == {"ok": True}
        mock.assert_awaited_once_with(["gh"])
