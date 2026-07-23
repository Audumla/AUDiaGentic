"""Error-construction guardrails for the shared foundation MCP layer."""
from __future__ import annotations

import ast
from pathlib import Path


def test_foundation_mcp_uses_canonical_error_factories() -> None:
    source_root = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "audiagentic"
        / "foundation"
        / "mcp"
    )
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "AudiaGenticError"
            ):
                violations.append(f"{path.relative_to(source_root)}:{node.lineno}")

    assert not violations, (
        "foundation MCP code must construct canonical errors via make_error() or "
        "make_error_factory(), not AudiaGenticError() directly:\n  "
        + "\n  ".join(violations)
    )
