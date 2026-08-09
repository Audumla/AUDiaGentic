"""AS61 architecture invariants for Role.

Checked by source inspection rather than behaviour, per this repo's
established pattern (see foundation/composition's own architecture tests):
a boundary violation is a defect a passing behavioural test would not notice.
"""
from __future__ import annotations

import ast

from audiagentic.foundation.paths.package import PACKAGE_ROOT

_ROLES_MODULE = PACKAGE_ROOT / "components" / "agents" / "models" / "role.py"
_PROVIDERS_PKG = PACKAGE_ROOT / "components" / "providers"


def _agents_imports(source: str) -> set[str]:
    """Return concrete agents-package imports from Python source."""
    imports: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(
                alias.name for alias in node.names if alias.name.startswith("audiagentic.components.agents")
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("audiagentic.components.agents"):
                imports.add(module)
    return imports


def test_providers_do_not_import_the_agents_role_domain() -> None:
    """Providers remain below agents; unrelated uses of the word role are irrelevant."""
    violations: dict[str, set[str]] = {}
    for path in sorted(_PROVIDERS_PKG.rglob("*.py")):
        imports = _agents_imports(path.read_text(encoding="utf-8", errors="ignore"))
        if imports:
            violations[path.relative_to(PACKAGE_ROOT).as_posix()] = imports
    assert violations == {}


def test_agents_import_scanner_targets_imports_not_incidental_text() -> None:
    assert _agents_imports("role = 'assistant'  # audiagentic.components.agents") == set()
    assert _agents_imports("from audiagentic.components.agents.models.role import Role") == {
        "audiagentic.components.agents.models.role"
    }


def test_role_domain_code_imports_no_concrete_store_or_composition() -> None:
    """Role storage is deliberately not composed (AS61 step 7) -- roles.py stays
    ordinary Python with no graph lookup and no concrete-store import beyond
    its own I/O boundary."""
    text = _ROLES_MODULE.read_text(encoding="utf-8")
    assert "audiagentic.foundation.composition" not in text
    assert ".root(" not in text
    assert "get_gateway_registry" not in text


def test_role_has_no_provider_model_or_runtime_fields() -> None:
    """Acceptance criteria: no provider/runtime configuration leaks into Role."""
    from audiagentic.components.agents.models.role import Role

    fields = set(Role.__dataclass_fields__)
    forbidden = {"provider_id", "model_id", "model_alias", "params", "is_default"}
    assert fields & forbidden == set()
