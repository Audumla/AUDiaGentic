"""DW02: git and forge access is owned by source_control behind two named public APIs."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "audiagentic"
SC = "audiagentic.components.source_control"
PUBLIC = {f"{SC}.git_api", f"{SC}.forge_api"}
INTERNAL = {f"{SC}.git_access", f"{SC}.forge_access"}
REMOVED = {"audiagentic.foundation.system.git", "audiagentic.foundation.system.forge"}


def _modules():
    for path in sorted(SRC.rglob("*.py")):
        module = ".".join(path.relative_to(SRC.parent).with_suffix("").parts)
        yield module, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported(tree: ast.AST) -> set[str]:
    """Every module name an import statement can reach, including ``from pkg import module``."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def test_foundation_no_longer_has_git_or_forge_modules() -> None:
    assert not (SRC / "foundation" / "system" / "git.py").exists()
    assert not (SRC / "foundation" / "system" / "forge.py").exists()
    offenders = [m for m, tree in _modules() if _imported(tree) & REMOVED]
    assert offenders == []


def test_only_source_control_imports_its_internal_access_modules() -> None:
    offenders = [
        m for m, tree in _modules()
        if not m.startswith(f"{SC}.") and _imported(tree) & INTERNAL
    ]
    assert offenders == []


def test_foundation_does_not_import_source_control() -> None:
    offenders = [
        m for m, tree in _modules()
        if m.startswith("audiagentic.foundation.") and any(i.startswith(SC) for i in _imported(tree))
    ]
    assert offenders == []


def test_public_apis_name_their_operations_and_hide_run_git() -> None:
    for name in ("git_api", "forge_api"):
        module = __import__(f"{SC}.{name}", fromlist=["__all__"])
        assert all(hasattr(module, item) for item in module.__all__)
        assert "run_git" not in module.__all__
        assert not hasattr(module, "run_git")


def test_no_alias_or_reexport_of_the_removed_modules() -> None:
    text = (SRC / "foundation" / "system" / "__init__.py").read_text(encoding="utf-8")
    assert "git" not in text and "forge" not in text
