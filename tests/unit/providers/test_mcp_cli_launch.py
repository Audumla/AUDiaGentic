from __future__ import annotations

import sys
import types

from audiagentic.commands.mcp import cmd_mcp
from audiagentic.launcher import _main


def test_cmd_mcp_imports_module_and_calls_main(monkeypatch) -> None:
    captured: dict[str, list[str]] = {}
    module = types.ModuleType("tests.fake_mcp_server")

    def main() -> int:
        captured["argv"] = list(sys.argv)
        return 0

    module.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tests.fake_mcp_server", module)

    assert cmd_mcp("tests.fake_mcp_server", ["--flag", "value"]) == 0
    assert captured["argv"] == ["tests.fake_mcp_server", "--flag", "value"]


def test_cmd_mcp_restores_argv(monkeypatch) -> None:
    old_argv = ["audiagentic", "mcp"]
    monkeypatch.setattr(sys, "argv", old_argv.copy())
    module = types.ModuleType("tests.fake_mcp_server_restore")

    def main() -> None:
        return None

    module.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tests.fake_mcp_server_restore", module)

    assert cmd_mcp("tests.fake_mcp_server_restore", []) == 0
    assert sys.argv == old_argv


def test_launcher_accepts_mcp_subcommand(monkeypatch, tmp_path) -> None:
    module = types.ModuleType("tests.fake_mcp_server_cli")

    def main() -> int:
        return 0

    module.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tests.fake_mcp_server_cli", module)

    assert _main(["--project", str(tmp_path), "mcp", "tests.fake_mcp_server_cli"]) == 0
