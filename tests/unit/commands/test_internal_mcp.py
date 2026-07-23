from __future__ import annotations

import sys
from types import SimpleNamespace

from audiagentic.commands.internal import cmd_mcp


def test_cmd_mcp_imports_module_and_restores_argv(monkeypatch, tmp_path) -> None:
    observed: list[str] = []

    def main() -> int:
        observed.extend(sys.argv)
        return 0

    monkeypatch.setattr("audiagentic.commands.internal.importlib.import_module", lambda _name: SimpleNamespace(main=main))
    original = sys.argv
    args = SimpleNamespace(module="example.mcp", module_args=["--flag", "value"])

    assert cmd_mcp(args, tmp_path) == 0
    assert observed == ["example.mcp", "--flag", "value"]
    assert sys.argv is original
