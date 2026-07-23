"""Provider platform code must not depend on runtime orchestration."""
from __future__ import annotations

import ast
from pathlib import Path

PROVIDERS_ROOT = Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "components" / "providers"


def test_provider_platform_has_no_runtime_harness_imports() -> None:
    violations: list[str] = []
    for path in sorted(PROVIDERS_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("audiagentic.runtime.harness"):
                        violations.append(f"{path.relative_to(PROVIDERS_ROOT)}:{node.lineno}: {alias.name}")
            if module.startswith("audiagentic.runtime.harness"):
                violations.append(f"{path.relative_to(PROVIDERS_ROOT)}:{node.lineno}: {module}")
    assert violations == [], "provider -> runtime.harness dependency violations:\n" + "\n".join(violations)
