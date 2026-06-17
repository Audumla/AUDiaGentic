"""Guardrail: core component root modules should live in component folders."""

from __future__ import annotations

from pathlib import Path

import pytest

_CORE_ROOT = Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "components" / "core"


def test_core_component_root_modules_are_folder_based() -> None:
    violations: list[str] = []
    for path in sorted(_CORE_ROOT.glob("*.py")):
        if path.name != "__init__.py":
            rel = path.relative_to(_CORE_ROOT.parent.parent.parent)
            violations.append(str(rel))

    if violations:
        report = "\n  ".join(violations)
        pytest.fail(
            "Flat core component root modules found.\n"
            "Move core component modules into component-specific folders:\n\n"
            f"  {report}"
        )
