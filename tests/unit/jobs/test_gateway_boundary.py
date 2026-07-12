"""Architecture-boundary test: agent_jobs accesses the gateway via events only (EDJ13).

Parses every non-test module under components/agent_jobs and fails on any
import or attribute reference to the gateway's Python API surface. Gateway
event topic string literals are the only permitted coupling.
"""
from __future__ import annotations

import ast
from pathlib import Path

_AGENT_JOBS_ROOT = (
    Path(__file__).resolve().parents[3]
    / "src" / "audiagentic" / "components" / "agent_jobs"
)

_FORBIDDEN_MODULES = (
    "agents_gateway_api",
    "agents_gateway_queue",
    "agents_gateway_store",
    "agents_gateway_dispatch",
    "agents_gateway_events",
)


def _inspected_files() -> list[Path]:
    files = sorted(_AGENT_JOBS_ROOT.rglob("*.py"))
    assert files, f"no agent_jobs modules found under {_AGENT_JOBS_ROOT}"
    return files


def _violations_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(m in alias.name for m in _FORBIDDEN_MODULES):
                    violations.append(f"{path.name}:{node.lineno} import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = ", ".join(a.name for a in node.names)
            if any(m in module for m in _FORBIDDEN_MODULES):
                violations.append(f"{path.name}:{node.lineno} from {module} import {names}")
            elif any(any(m in a.name for m in _FORBIDDEN_MODULES) for a in node.names):
                violations.append(f"{path.name}:{node.lineno} from {module} import {names}")
        elif isinstance(node, ast.Attribute):
            if node.attr in _FORBIDDEN_MODULES:
                violations.append(f"{path.name}:{node.lineno} attribute {node.attr}")
        elif isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_MODULES:
                violations.append(f"{path.name}:{node.lineno} name {node.id}")
    return violations


def test_agent_jobs_scope_is_enumerated():
    """Every agent_jobs module is in scope — a future module cannot evade the check."""
    files = _inspected_files()
    names = {f.relative_to(_AGENT_JOBS_ROOT).as_posix() for f in files}
    # Spot-check known members so an accidental root-path change fails loudly.
    for expected in ("event_observer.py", "event_triggers.py", "control.py", "prompt_launch.py"):
        assert expected in names, f"expected {expected} in inspected scope; got {sorted(names)}"


def test_agent_jobs_never_imports_gateway_python_api():
    all_violations: list[str] = []
    for path in _inspected_files():
        all_violations.extend(_violations_in(path))
    assert not all_violations, (
        "agent_jobs must access the gateway via published events only "
        "(EDJ04/EDJ13); forbidden gateway references found:\n"
        + "\n".join(all_violations)
    )


def test_detector_catches_forbidden_import(tmp_path: Path):
    """The detector itself works: a scratch module with a forbidden import fails."""
    scratch = tmp_path / "scratch.py"
    scratch.write_text(
        "from audiagentic.components.agents import agents_gateway_api\n",
        encoding="utf-8",
    )
    assert _violations_in(scratch), "detector failed to flag a forbidden import"
