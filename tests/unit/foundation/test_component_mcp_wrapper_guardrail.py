"""Guardrail: optional component MCP wrappers may only import same-component *_api modules."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "audiagentic"
_OPTIONAL_ROOT = _SRC_ROOT / "components" / "optional"


def _component_name(path: Path) -> str:
    return path.relative_to(_OPTIONAL_ROOT).parts[0]


def _same_component_imports(path: Path) -> set[str]:
    component = _component_name(path)
    package_prefix = f"audiagentic.components.optional.{component}"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1:
                if node.module:
                    imports.add(node.module.split(".", 1)[0])
                else:
                    imports.update(alias.name.split(".", 1)[0] for alias in node.names)
                continue
            if node.module == package_prefix:
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
                continue
            if node.module and node.module.startswith(package_prefix + "."):
                imports.add(node.module[len(package_prefix) + 1 :].split(".", 1)[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(package_prefix + "."):
                    imports.add(alias.name[len(package_prefix) + 1 :].split(".", 1)[0])
    imports.discard(path.stem)
    return imports


def test_optional_component_mcp_wrappers_only_import_component_api_modules() -> None:
    violations: list[str] = []
    for path in sorted(_OPTIONAL_ROOT.rglob("*_mcp.py")):
        for imported_module in sorted(_same_component_imports(path)):
            if not imported_module.endswith("_api"):
                rel = path.relative_to(_SRC_ROOT.parent)
                violations.append(f"{rel} imports {imported_module}")

    if violations:
        report = "\n  ".join(violations)
        pytest.fail(
            "Optional component MCP wrappers import same-component non-API modules.\n"
            "Move orchestration into component-specific *_api modules instead:\n\n"
            f"  {report}"
        )
