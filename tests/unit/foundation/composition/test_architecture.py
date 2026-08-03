"""AS59 Stage 1 architecture invariants.

These are the rules that stop composition drifting into the thing AS59's
"Non-Negotiable Rules" forbid: a service locator with a runtime `get()`, a
hidden global container, or a second way to execute code from YAML.

They are checked by inspecting source rather than by exercising behaviour,
because a violation is an architectural defect that a passing behavioural test
would not notice.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from audiagentic.foundation.composition import build_graph, parse_composition_config
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.paths.package import PACKAGE_ROOT
from audiagentic.runtime.bootstrap.composition import _pkg_default_path, builtin_contributions

_COMPOSITION_PKG = PACKAGE_ROOT / "foundation" / "composition"
_COMPOSITION_ROOT_PKG = PACKAGE_ROOT / "runtime" / "bootstrap"


def _module_paths(package: Path) -> list[Path]:
    return sorted(p for p in package.glob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_foundation_composition_imports_no_component_or_runtime_code() -> None:
    """§1: foundation must not depend on components or runtime orchestration."""
    offenders: dict[str, set[str]] = {}
    for path in _module_paths(_COMPOSITION_PKG):
        bad = {
            module
            for module in _imported_modules(path)
            if module.startswith(("audiagentic.components", "audiagentic.runtime"))
        }
        if bad:
            offenders[path.name] = bad
    assert offenders == {}


def _identifiers(path: Path) -> set[str]:
    """Identifiers defined or referenced in a module.

    Deliberately excludes comments, docstrings and import module names: prose
    may *name* a domain concept (the package docstring lists the scopes this
    facility does not implement), while an identifier naming one would mean the
    facility had grown a special case.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def test_foundation_composition_is_domain_blind() -> None:
    """Composition must not learn what a service is.

    A domain concept named by an identifier here would mean the facility had
    grown a special case for one kind of service, which is how a generic seam
    becomes a dispatcher.
    """
    domain_words = ("gateway", "provider", "harness", "agent", "session", "queue")
    offenders: dict[str, list[str]] = {}
    for path in _module_paths(_COMPOSITION_PKG):
        hits = sorted(
            name
            for name in _identifiers(path)
            # The package name itself contains "agent"; it is not a domain word here.
            if any(word in name.lower().replace("audiagentic", "") for word in domain_words)
        )
        if hits:
            offenders[path.name] = hits
    assert offenders == {}


def test_the_built_graph_exposes_no_runtime_lookup() -> None:
    """No `get()`: the graph hands over configured roots, and nothing else."""
    from audiagentic.foundation.composition.graph import BuiltGraph

    public = {name for name in vars(BuiltGraph) if not name.startswith("_")}
    assert public == {"root", "shutdown", "construction_order"}


def test_only_the_composition_root_reads_bindings() -> None:
    """`bindings` is composition-root wiring, not an API other code consults."""
    readers: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if _COMPOSITION_PKG in path.parents or _COMPOSITION_ROOT_PKG in path.parents:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if ".bindings" in text or "load_composition_config" in text:
            readers.append(str(path.relative_to(PACKAGE_ROOT)))
    assert readers == []


def test_no_service_receives_the_graph_or_the_builder() -> None:
    """Core services never resolve from the graph, so none may import it."""
    importers: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if _COMPOSITION_PKG in path.parents or _COMPOSITION_ROOT_PKG in path.parents:
            continue
        if "audiagentic.foundation.composition" in _imported_modules(path):
            importers.append(str(path.relative_to(PACKAGE_ROOT)))
    assert importers == []


def test_the_launcher_is_the_only_caller_of_the_composition_root() -> None:
    """One process adopts the host in Stage 1; later roots are deliberate."""
    callers: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if _COMPOSITION_ROOT_PKG in path.parents:
            continue
        if "build_application_graph" in path.read_text(encoding="utf-8", errors="ignore"):
            callers.append(str(path.relative_to(PACKAGE_ROOT)))
    assert callers == ["launcher.py"]


def test_only_the_application_host_installs_the_interaction_backend() -> None:
    """A migrated service leaves the legacy exemption permanently.

    `set_backend` is the one startup path Stage 1 actually migrated, so it is
    the one that must have no second caller. The startup paths still called
    from elsewhere (`logging.bootstrap` from the MCP servers,
    `register_harness_status` from `runtime/harness`) remain under the bounded
    legacy exemption and are listed in AS59's exemption register with owners —
    they are deliberately not asserted here, because asserting them would claim
    a migration that has not happened.
    """
    callers: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if _COMPOSITION_ROOT_PKG in path.parents:
            continue
        # The owning module defines and re-exports it; that is not a call site.
        if path.parts[-2:] == ("interaction", "backend.py") or path.parts[-2:] == (
            "interaction",
            "__init__.py",
        ):
            continue
        if "set_backend(" in path.read_text(encoding="utf-8", errors="ignore"):
            callers.append(str(path.relative_to(PACKAGE_ROOT)))
    assert callers == []


def test_the_packaged_composition_config_names_no_python_paths() -> None:
    """Parsing enforces this; this test proves the shipped file satisfies it."""
    config = parse_composition_config(load_yaml_file(_pkg_default_path()))
    assert config.roots
    for service_id, implementation_id in config.bindings.items():
        for value in (str(service_id), str(implementation_id)):
            assert ".py" not in value
            assert ":" not in value
            assert "_" not in value


def test_the_packaged_config_and_the_builtin_contributions_agree() -> None:
    """A binding naming something no code contributes must fail the build."""
    config = parse_composition_config(load_yaml_file(_pkg_default_path()))
    graph = build_graph(builtin_contributions(), config)
    graph.shutdown()


def test_every_composition_error_code_is_registered() -> None:
    """§4: a public failure needs a stable, registered code.

    Asserted against the owning component's error-resolutions.yaml rather than
    the in-process resolution table, because that table is only populated once
    components register — so an in-process check would pass vacuously in a bare
    unit run. Guards the AS72 failure mode: an error path that only blows up as
    an unregistered-code ValueError the first time it is genuinely hit.
    """
    resolutions = load_yaml_file(
        PACKAGE_ROOT / "config" / "components" / "foundation" / "error-resolutions.yaml"
    )
    codes = [f"VAL-COMPOSE-{n:03d}" for n in range(1, 8)] + ["CON-COMPOSE-001"]
    unregistered = [code for code in codes if code not in resolutions]
    assert unregistered == []


@pytest.mark.parametrize(
    "value",
    ["pkg.mod:Attr", "a/b.py", "audiagentic.runtime.Bootstrap", "has_underscore"],
)
def test_code_references_are_rejected_by_validation_not_only_by_review(value: str) -> None:
    with pytest.raises(AudiaGenticError) as exc:
        parse_composition_config({"composition": {"roots": [value]}})
    assert exc.value.code == "VAL-COMPOSE-002"
