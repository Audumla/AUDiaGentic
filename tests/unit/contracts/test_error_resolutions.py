"""Tests for error resolution loading and lookup."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

from audiagentic.foundation.contracts.error_resolutions import (
    load_all_error_resolutions,
    load_error_resolutions_from_component,
)
from audiagentic.foundation.contracts.errors import (
    ERROR_CODE_PATTERN,
    AudiaGenticError,
    _mark_error_resolutions_loaded,
    get_error_resolution,
    register_error_resolution,
)


def test_get_error_resolution_returns_registered() -> None:
    register_error_resolution("TEST-001", "test resolution")
    assert get_error_resolution("TEST-001") == "test resolution"


def test_get_error_resolution_returns_none_for_unregistered() -> None:
    assert get_error_resolution("NONEXISTENT-001") is None


def test_load_all_error_resolutions_populates_registry() -> None:
    config_dirs = [Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components"]
    load_all_error_resolutions(config_dirs)

    assert get_error_resolution("VAL-PPARSE-001") is not None
    assert get_error_resolution("VAL-COMPLETE-001") is not None
    assert get_error_resolution("CON-ARCHIVE-001") is not None
    assert get_error_resolution("IO-JOBSTORE-001") is not None
    assert get_error_resolution("VAL-PROJFILE-001") is not None


def test_load_error_resolutions_from_component_returns_count() -> None:
    config_dir = Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components"
    count = load_error_resolutions_from_component("project", config_dir)
    assert count == 6


def test_unregistered_error_code_blocked_after_load() -> None:
    """After load_all_error_resolutions, an unregistered code raises ValueError."""
    _mark_error_resolutions_loaded()
    with pytest.raises(ValueError, match="not registered"):
        AudiaGenticError(
            code="VAL-UNKNOWN-001",
            kind="providers",
            message="this code is not registered",
        )


def test_registered_error_code_allowed_after_load() -> None:
    """A registered code can still be instantiated after load."""
    config_dirs = [Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components"]
    load_all_error_resolutions(config_dirs)
    err = AudiaGenticError(
        code="VAL-PCFG-001",
        kind="providers",
        message="provider config failed validation",
    )
    assert err.code == "VAL-PCFG-001"


def test_every_provider_error_code_literal_has_a_resolution() -> None:
    """Codes returned as typed-result strings must still be catalogued.

    AudiaGenticError rejects unregistered codes at construction, but the
    provider automation families carry codes as plain ``error_code="..."``
    strings on their typed results, so that guard never fires for them. This
    scan is what keeps those codes in the config-owned catalogue.
    """
    repo_root = Path(__file__).resolve().parents[3]
    config_dirs = [repo_root / "src" / "audiagentic" / "config" / "components"]
    load_all_error_resolutions(config_dirs)

    providers_src = repo_root / "src" / "audiagentic" / "components" / "providers"
    pattern = re.compile(r"\"((?:VAL|CON|RES|IO|INT|EXT|TO)-[A-Z]{2,8}-\d{3})\"")

    emitted: dict[str, str] = {}
    for path in providers_src.rglob("*.py"):
        for code in pattern.findall(path.read_text(encoding="utf-8")):
            emitted.setdefault(code, str(path.relative_to(repo_root)))

    assert emitted, "scan found no provider error codes — check the pattern"
    missing = sorted(
        f"{code} (emitted by {source})"
        for code, source in emitted.items()
        if get_error_resolution(code) is None
    )
    assert not missing, (
        "provider error codes emitted in code but absent from "
        "config/components/providers/error-resolutions.yaml:\n  "
        + "\n  ".join(missing)
    )


def test_every_registered_error_code_matches_the_canonical_format() -> None:
    """AS72 step 4: a registered code with a lowercase component segment is
    silently unreachable — ``make_error`` always uppercases its ``component``
    argument when building the real code, so a lowercase registry key can
    never match what's actually raised. Found via direct construction-path
    audit: 13 real codes (release/session components) had their resolution
    text stranded under a lowercase key this way before this test existed.

    This scans every error-resolutions.yaml file directly (not the loaded
    registry — a collision during load could silently shadow a bad key with
    a good one from another file and mask the defect)."""
    repo_root = Path(__file__).resolve().parents[3]
    config_dirs = repo_root / "src" / "audiagentic" / "config" / "components"

    violations: list[str] = []
    for resolutions_file in sorted(config_dirs.rglob("error-resolutions.yaml")):
        data = yaml.safe_load(resolutions_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        for code in data:
            if not ERROR_CODE_PATTERN.match(code):
                violations.append(f"{resolutions_file.relative_to(repo_root)}: {code!r}")

    assert not violations, (
        "Registered error codes with a non-canonical format (expected "
        "PREFIX-COMPONENT-NNN, all-uppercase segments) — these are silently "
        "unreachable because make_error() always uppercases the component it "
        "builds the real code from:\n  " + "\n  ".join(violations)
    )


def _literal_str(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _literal_int(node: ast.expr | None) -> int | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, int) else None


def _call_func_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_every_statically_resolvable_make_error_code_has_a_resolution() -> None:
    """AS72 step 2: ``make_error(prefix=, component=, number=)`` and the
    ``make_error_factory(prefix, component, kind)`` closures it returns never
    appear as a literal code string anywhere — the code is assembled from
    ``f\"{prefix}-{component.upper()}-{number:03d}\"`` at call time. Neither
    ``test_every_provider_error_code_literal_has_a_resolution`` nor
    ``test_every_foundation_error_code_literal_has_a_resolution`` (both
    literal-string regex scans) can ever see these — this is the third,
    separate construction path AS72 found was never covered. Confirmed by
    direct audit: 33 real codes were unregistered this way before this test
    existed, none caught by the existing literal-string scans.

    Factory bindings are resolved same-module only (confirmed by direct grep
    audit: no ``make_error_factory``-bound name is ever imported into another
    module in this codebase — all ~48 bindings are module-private helpers).
    Call sites with a non-literal ``number`` are dynamically numbered and are
    a separate, larger static-analysis problem (AS72's own step 3) — they are
    counted here but not required to resolve, so this test's coverage claim
    stays honest about what it actually checks.
    """
    repo_root = Path(__file__).resolve().parents[3]
    src = repo_root / "src" / "audiagentic"
    config_dirs = repo_root / "src" / "audiagentic" / "config" / "components"
    load_all_error_resolutions([config_dirs])

    trees: dict[Path, ast.AST] = {}
    for path in src.rglob("*.py"):
        try:
            trees[path] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue

    # Pass 1: collect make_error_factory(prefix, component, kind) bindings,
    # keyed by (defining file, local name) -- same-module resolution only.
    factory_bindings: dict[tuple[Path, str], tuple[str, str]] = {}
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
                continue
            call = node.value
            if _call_func_name(call) != "make_error_factory":
                continue
            args = call.args
            kwargs = {kw.arg: kw.value for kw in call.keywords}
            prefix = _literal_str(args[0]) if args else _literal_str(kwargs.get("prefix"))
            component = _literal_str(args[1]) if len(args) > 1 else _literal_str(kwargs.get("component"))
            if prefix and component:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        factory_bindings[(path, target.id)] = (prefix, component)

    # Pass 2: resolve direct make_error(...) calls and factory-bound calls.
    resolvable: dict[str, str] = {}
    for path, tree in trees.items():
        local_factories = {
            name: pc for (fp, name), pc in factory_bindings.items() if fp == path
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = _call_func_name(node)
            if fname == "make_error":
                kwargs = {kw.arg: kw.value for kw in node.keywords}
                prefix = _literal_str(kwargs.get("prefix"))
                component = _literal_str(kwargs.get("component"))
                number = _literal_int(kwargs.get("number"))
                if prefix and component and number is not None:
                    resolvable.setdefault(
                        f"{prefix}-{component.upper()}-{number:03d}", str(path.relative_to(repo_root))
                    )
            elif fname in local_factories:
                prefix, component = local_factories[fname]
                number = _literal_int(node.args[0]) if node.args else None
                if number is not None:
                    resolvable.setdefault(
                        f"{prefix}-{component.upper()}-{number:03d}", str(path.relative_to(repo_root))
                    )


    assert resolvable, "AST scan found no make_error()/factory call sites — check the walk logic"

    missing = sorted(
        f"{code} (constructed in {source})"
        for code, source in resolvable.items()
        if get_error_resolution(code) is None
    )
    assert not missing, (
        "make_error()/make_error_factory() codes constructed in code but absent "
        "from the error catalogue:\n  " + "\n  ".join(missing)
    )


def test_dynamic_make_error_numbers_are_not_mistaken_for_catalogue_entries() -> None:
    """The scanner must remain conservative for runtime-computed numbers."""
    tree = ast.parse(
        "make_error(prefix='VAL', component='X', number=code_number, "
        "kind='test', message='x')"
    )
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    kwargs = {kw.arg: kw.value for kw in call.keywords}
    assert _literal_int(kwargs["number"]) is None


def test_every_foundation_error_code_literal_has_a_resolution() -> None:
    """Foundation typed results and constants cannot bypass runtime validation."""
    repo_root = Path(__file__).resolve().parents[3]
    load_all_error_resolutions(
        [repo_root / "src" / "audiagentic" / "config" / "components"]
    )
    foundation_src = repo_root / "src" / "audiagentic" / "foundation"
    pattern = re.compile(
        r'["\']((?:VAL|CON|RES|IO|INT|EXT|TO|CFG|VER|NET|UNS)-'
        r'[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-\d{3})["\']'
    )
    emitted: dict[str, str] = {}
    for path in foundation_src.rglob("*.py"):
        for code in pattern.findall(path.read_text(encoding="utf-8")):
            emitted.setdefault(code, str(path.relative_to(repo_root)))

    missing = sorted(
        f"{code} (emitted by {source})"
        for code, source in emitted.items()
        if get_error_resolution(code) is None
    )
    assert not missing, (
        "foundation error codes emitted in code but absent from the error catalogue:\n  "
        + "\n  ".join(missing)
    )

