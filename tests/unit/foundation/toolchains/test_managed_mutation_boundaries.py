"""MA01 managed-mutation inventory and architecture guardrails."""
from __future__ import annotations

import ast
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
SRC_ROOT = WORKSPACE_ROOT / "src" / "audiagentic"
AUDIT_PATH = WORKSPACE_ROOT / "docs" / "reference" / "MANAGED_MUTATION_AUDIT.md"

_SCOPES = (
    "components/memory/hindsight",
    "components/providers/adapters",
    "components/providers/services/managed_mcp_registry.py",
    "components/providers/surfaces",
    "components/providers/skill_surfaces.py",
    "runtime/harness/opencode/install",
    "runtime/harness/pi/install",
    "runtime/harness/pi/mcp_format.py",
    "components/source_control/source_control_bootstrap.py",
    "components/release/release_please",
)
_MUTATIONS = {
    "atomic_write_json",
    "atomic_write_text",
    "copyfile",
    "copytree",
    "dump_config",
    "rmdir",
    "rmtree",
    "save_yaml_file",
    "unlink",
    "write_bytes",
    "write_text",
}
_CATEGORIES = {
    "adapter-serializer",
    "component-managed",
    "generated-surface",
    "runtime-asset",
    "shared-config",
    "third-party-repair",
}


def _in_scope(relative: str) -> bool:
    return any(
        relative == scope or relative.startswith(scope.rstrip("/") + "/")
        for scope in _SCOPES
    )


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _enclosing_symbol(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return "<module>"


def scan_mutation_inventory() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(SRC_ROOT.rglob("*.py")):
        relative = path.relative_to(SRC_ROOT).as_posix()
        if not _in_scope(relative):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = _parent_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name not in _MUTATIONS:
                continue
            symbol = _enclosing_symbol(node, parents)
            key = f"src/audiagentic/{relative}:{symbol}"
            found.setdefault(key, set()).add(name)
    return found


def read_audit_inventory() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for raw in AUDIT_PATH.read_text(encoding="utf-8").splitlines():
        if not raw.startswith("| src/audiagentic/"):
            continue
        cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
        assert len(cells) == 6, f"malformed managed-mutation row: {raw}"
        key, mutations, category, primitive, action, rationale = cells
        assert key not in rows, f"duplicate managed-mutation row: {key}"
        rows[key] = {
            "mutations": mutations,
            "category": category,
            "primitive": primitive,
            "action": action,
            "rationale": rationale,
        }
    return rows


def direct_spec_calls(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"writer", "remover"}
    }


def provider_literal_branches(source: str) -> set[str]:
    """Return provider ids used in direct equality/membership branch tests."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Compare, ast.If)):
            continue
        expression = node.test if isinstance(node, ast.If) else node
        text = ast.unparse(expression)
        if "provider_id" not in text and ".provider_id" not in text:
            continue
        for child in ast.walk(expression):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                found.add(child.value)
    return found


def component_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return {name for name in imports if name.startswith("audiagentic.components.")}


def test_inventory_exactly_matches_scanner() -> None:
    scanned = scan_mutation_inventory()
    audited = read_audit_inventory()
    assert set(audited) == set(scanned), (
        "managed mutation inventory drift\n"
        f"unaudited: {sorted(set(scanned) - set(audited))}\n"
        f"stale: {sorted(set(audited) - set(scanned))}"
    )
    for key, operations in scanned.items():
        documented = set(audited[key]["mutations"].split(","))
        assert documented == operations, f"mutation operation drift for {key}"


def test_inventory_rows_have_actionable_classification() -> None:
    for key, row in read_audit_inventory().items():
        assert row["category"] in _CATEGORIES, key
        assert row["primitive"], key
        assert row["action"], key
        assert row["rationale"].endswith("."), key


def test_direct_managed_spec_calls_are_core_or_recorded_violation() -> None:
    # MO06 closed: lsp_projection.py no longer calls spec.writer/remover
    # directly — it routes through apply_managed_config_write/remove, the
    # sanctioned indirection point in foundation/toolchains/managed_config.py.
    # RV509 closed the plugin_entries.py exemption: it now routes mutations
    # through sync_managed_config and keeps only a status-mode spec.reader.
    # Equality (not subset) so a stale allowlist entry fails loudly instead
    # of silently weakening the guard.
    allowed_core = {
        "src/audiagentic/components/providers/services/mcp.py",
        "src/audiagentic/foundation/toolchains/managed_config.py",
    }
    found: dict[str, set[str]] = {}
    for path in sorted(SRC_ROOT.rglob("*.py")):
        calls = direct_spec_calls(path.read_text(encoding="utf-8"))
        if calls:
            found[path.relative_to(WORKSPACE_ROOT).as_posix()] = calls
    assert set(found) == allowed_core, found


def test_generic_hindsight_builder_provider_branches_are_pinned() -> None:
    path = SRC_ROOT / "components" / "memory" / "hindsight" / "strategies.py"
    # Existing MA02 debt is pinned exactly so another provider branch fails MA01 guard.
    assert provider_literal_branches(path.read_text(encoding="utf-8")) == {
        "aider",
        "codex",
        "pi",
    }


def test_generic_specs_component_type_leak_is_pinned() -> None:
    # MO06 closed: ManagedConfigSpec's reader/writer/remover are Any-typed
    # (domain-opaque, matching fragments.py), so base.py no longer needs to
    # import coding_lsp.LanguageServerEntry for a type hint.
    path = SRC_ROOT / "components" / "providers" / "descriptors" / "base.py"
    leaks = component_imports(path.read_text(encoding="utf-8"))
    assert leaks == set()


def test_no_second_managed_registry_implementation() -> None:
    definitions: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name.startswith("load_managed_") and node.name.endswith("_registry")
                or node.name.startswith("save_managed_") and node.name.endswith("_registry")
            ):
                definitions.append(
                    f"{path.relative_to(WORKSPACE_ROOT).as_posix()}:{node.name}"
                )
    assert definitions == [
        "src/audiagentic/components/providers/services/managed_mcp_registry.py:load_managed_mcp_registry",
        "src/audiagentic/components/providers/services/managed_mcp_registry.py:save_managed_mcp_registry",
    ]


def test_negative_fixtures_detect_violations() -> None:
    assert direct_spec_calls("def f(spec, p): spec.writer(p, {})") == {"writer"}
    assert provider_literal_branches(
        "def f(row):\n    if row.provider_id == 'codex':\n        return 1\n"
    ) == {"codex"}
    assert component_imports(
        "from audiagentic.components.coding_lsp.language_servers import Entry"
    ) == {"audiagentic.components.coding_lsp.language_servers"}


def test_positive_fixtures_allow_valid_segregation() -> None:
    adapter = "def write_format(path, entries): atomic_write_json(path, entries)"
    domain_store = "def write_record(path, record): atomic_write_json(path, record)"
    renderer = "def render(value): return {'path': value}"
    third_party_repair = "def repair(target): atomic_write_text(target, 'patched')"
    for source in (adapter, domain_store, renderer, third_party_repair):
        assert direct_spec_calls(source) == set()
        assert provider_literal_branches(source) == set()
        assert component_imports(source) == set()
