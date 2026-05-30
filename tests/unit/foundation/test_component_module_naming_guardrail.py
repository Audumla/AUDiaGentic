"""Guardrail: optional component root modules must use component-specific names."""

from __future__ import annotations

from pathlib import Path

import pytest

_OPTIONAL_ROOT = Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "components" / "optional"
_BANNED_ROOT_FILENAMES = {
    "api.py",
    "bootstrap.py",
    "config.py",
    "manage_mcp.py",
    "mcp_server.py",
    "session_manager.py",
}


def test_optional_component_root_modules_use_component_prefixes() -> None:
    violations: list[str] = []
    for component_dir in sorted(path for path in _OPTIONAL_ROOT.iterdir() if path.is_dir()):
        for path in sorted(component_dir.glob("*.py")):
            if path.name in _BANNED_ROOT_FILENAMES:
                rel = path.relative_to(_OPTIONAL_ROOT.parent.parent.parent)
                violations.append(str(rel))

    if violations:
        report = "\n  ".join(violations)
        pytest.fail(
            "Generic optional component root module names found.\n"
            "Rename them with component-specific prefixes:\n\n"
            f"  {report}"
        )
