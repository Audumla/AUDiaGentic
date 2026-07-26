"""Architecture regression tests for recipe ownership boundaries.

These tests verify that future changes do not reintroduce the ownership
violations that prompted the provider-recipe-refactor plan:
- foundation/toolchains must not import provider-specific modules
- foundation/toolchains must not contain MCP-specific helpers
- components/memory must not enumerate providers or import provider surface managers
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


def _get_python_files(directory: Path) -> list[Path]:
    """Get all Python files in a directory recursively."""
    if not directory.exists():
        return []
    return sorted(directory.rglob("*.py"))


def _get_imports(filepath: Path) -> list[str]:
    """Extract all import statements from a Python file."""
    with open(filepath, encoding="utf-8") as f:
        source = f.read()
    try:
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, SystemError, RecursionError):
        return []

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


class TestFoundationToolchainsBoundaries:
    """Verify foundation/toolchains remains provider-agnostic."""

    @pytest.fixture
    def toolchains_dir(self) -> Path:
        return WORKSPACE_ROOT / "src" / "audiagentic" / "foundation" / "toolchains"

    def test_no_provider_imports(self, toolchains_dir):
        """foundation/toolchains must not import from audiagentic.components.providers."""
        violations = []
        for pyfile in _get_python_files(toolchains_dir):
            imports = _get_imports(pyfile)
            for imp in imports:
                if "providers" in imp and imp.startswith("audiagentic.components.providers"):
                    violations.append(f"{pyfile.relative_to(WORKSPACE_ROOT)}: imports {imp}")
        assert not violations, "foundation/toolchains imports provider modules:\n" + "\n".join(
            violations
        )

    def test_no_mcp_specific_helpers_in_config_patcher(self, toolchains_dir):
        """ConfigPatcher must not have add_mcp_entry or remove_mcp_entry methods."""
        import pytest

        config_patcher = toolchains_dir / "config_patcher.py"
        if not config_patcher.exists():
            pytest.skip("config_patcher.py no longer exists")
        with open(config_patcher, encoding="utf-8") as f:
            source = f.read()
        assert "add_mcp_entry" not in source, (
            "ConfigPatcher still has add_mcp_entry — move to providers/services/mcp.py"
        )
        assert "remove_mcp_entry" not in source, (
            "ConfigPatcher still has remove_mcp_entry — move to providers/services/mcp.py"
        )

    def test_no_mcp_hooks_plugins_in_docstring(self, toolchains_dir):
        """recipe_contract.py docstring must not name MCP/hooks/plugins as foundation concepts."""
        recipe_contract = toolchains_dir / "recipe_contract.py"
        with open(recipe_contract, encoding="utf-8") as f:
            source = f.read()
        # The first docstring should not list MCP/hooks/plugins as examples
        docstring_start = source.find('"""')
        docstring_end = source.find('"""', docstring_start + 3)
        docstring = source[docstring_start:docstring_end]
        forbidden = ("MCP", "hook", "plugin", "language server", "provider")
        violations = [term for term in forbidden if term.lower() in docstring.lower()]
        assert not violations, (
            "recipe_contract.py docstring leaks component concepts: " + ", ".join(violations)
        )


class TestMemoryComponentBoundaries:
    """Verify components/memory does not orchestrate providers."""

    @pytest.fixture
    def memory_dir(self) -> Path:
        return WORKSPACE_ROOT / "src" / "audiagentic" / "components" / "memory"

    def test_no_provider_surface_manager_import(self, memory_dir):
        """memory_api must not import provider surface managers directly."""
        memory_api = memory_dir / "memory_api.py"
        with open(memory_api, encoding="utf-8") as f:
            source = f.read()
        forbidden = (
            "COMPONENT_" + "PROVIDERS",
            "apply_provider_surfaces",
            "providers.services",
            "surfaces.contributions",
            "hindsight_strategy",
            "build_memory_contributions",
        )
        violations = [term for term in forbidden if term in source]
        assert not violations, (
            "memory_api leaks provider orchestration/surface behavior: " + ", ".join(violations)
        )

    def test_hindsight_no_enabled_providers_option(self):
        """hindsight.yaml must not have enabled-providers option."""
        hindsight_config = (
            WORKSPACE_ROOT
            / "src"
            / "audiagentic"
            / "config"
            / "components"
            / "memory"
            / "hindsight.yaml"
        )
        with open(hindsight_config, encoding="utf-8") as f:
            source = f.read()
        assert "enabled-providers" not in source, (
            "hindsight.yaml still has enabled-providers — memory should not choose provider allowlist"
        )

    def test_no_memory_owned_hindsight_recipe(self, memory_dir):
        """Hindsight-specific logic must live only in the implementation package."""
        assert not (memory_dir / "hindsight_recipe.py").exists()
        assert (memory_dir / "hindsight").is_dir()

    def test_memory_core_has_no_provider_imports(self, memory_dir):
        """Only memory/hindsight may use controlled provider-facing recipe seams."""
        violations = []
        for pyfile in _get_python_files(memory_dir):
            if "hindsight" in pyfile.relative_to(memory_dir).parts:
                continue
            for imp in _get_imports(pyfile):
                if imp.startswith("audiagentic.components.providers"):
                    violations.append(f"{pyfile.relative_to(WORKSPACE_ROOT)}: imports {imp}")
        assert not violations

    def test_hindsight_provider_imports_are_contained(self, memory_dir):
        """Hindsight may depend only on generic provider seams, not provider services."""
        allowed = {
            "audiagentic.components.providers.providers_api",
            "audiagentic.components.providers.descriptors.registry",
            "audiagentic.components.providers.contracts.managed_hooks",
            "audiagentic.components.providers.contracts.managed_mcp",
        }
        violations = []
        for pyfile in _get_python_files(memory_dir / "hindsight"):
            for imp in _get_imports(pyfile):
                if imp.startswith("audiagentic.components.providers") and imp not in allowed:
                    violations.append(f"{pyfile.relative_to(WORKSPACE_ROOT)}: imports {imp}")
        assert not violations


class TestFoundationCapabilityCatalogDeleted:
    """RV405/RV406 — no capability vocabulary remains under foundation after deletion."""

    def test_no_capability_package_exists(self):
        """foundation/capability_catalog/ must not exist."""
        catalog_dir = WORKSPACE_ROOT / "src" / "audiagentic" / "foundation" / "capability_catalog"
        assert not catalog_dir.exists(), (
            f"foundation/capability_catalog/ still exists: {catalog_dir}"
        )

    def test_no_capability_symbols_under_foundation(self):
        """No Python file under foundation/ references capability vocabulary symbols."""
        forbidden = {
            "CapabilityRecord",
            "CAPABILITY_KINDS",
            "SUPPORT_STATES",
            "EVIDENCE_REVIEW_STATES",
            "OPERATION_NAMES",
            "MODE_VALUES",
            "SURFACE_TYPES",
            "OWNERSHIP_TYPES",
            "RELOAD_MODES",
            "DRY_RUN_MODES",
            "SECRETS_MODES",
            "TRANSPORT_KINDS",
            "SESSION_MODES",
            "EVENT_DELIVERY_MODES",
            "CANCELLATION_MODES",
            "PERMISSION_MODES",
            "LAUNCH_CLASS_TYPES",
            "TRANSPORT_STATES",
            "TransportManifestation",
            "Contract",
            "Manifestation",
            "ModeDeclaration",
        }
        foundation_dir = WORKSPACE_ROOT / "src" / "audiagentic" / "foundation"
        violations = []
        for pyfile in _get_python_files(foundation_dir):
            try:
                with open(pyfile, encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source, filename=str(pyfile))
            except (SyntaxError, SystemError, RecursionError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in forbidden:
                    violations.append(f"{pyfile.relative_to(WORKSPACE_ROOT)}: references {node.id}")
                elif isinstance(node, (ast.ImportFrom, ast.Import)):
                    # Check import targets
                    if isinstance(node, ast.ImportFrom) and node.module:
                        for sym in forbidden:
                            if sym in node.module:
                                violations.append(
                                    f"{pyfile.relative_to(WORKSPACE_ROOT)}: imports from {node.module}"
                                )
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name in forbidden:
                                violations.append(
                                    f"{pyfile.relative_to(WORKSPACE_ROOT)}: imports {alias.name}"
                                )
        assert not violations, (
            "Capability vocabulary found under foundation/ after deletion:\n"
            + "\n".join(violations)
        )


class TestRequesterProvidersImportAllowlist:
    """RV405 — requester components may import ONLY providers_api, never internals."""

    @pytest.fixture
    def allowed_providers_prefix(self):
        """The only allowed providers import prefix for requester components."""
        return "audiagentic.components.providers.providers_api"

    @pytest.fixture
    def requester_component_dirs(self):
        """Directories of requester components that must follow the allowlist.

        Excludes memory/hindsight subpackage — it has its own controlled allowlist test
        (TestMemoryComponentBoundaries.test_hindsight_provider_imports_are_contained).
        """
        return [
            WORKSPACE_ROOT / "src" / "audiagentic" / "components" / "coding_lsp",
            WORKSPACE_ROOT / "src" / "audiagentic" / "components" / "agent_jobs",
        ]

    def test_coding_lsp_providers_import_allowlist(
        self, allowed_providers_prefix, requester_component_dirs
    ):
        """coding-lsp may import only from providers_api; never adapters/services internals.

        No allowlisted violations remain: MA08's coding-lsp boundary is clean.
        The contract types are exported through providers_api, and the
        descriptor/enablement fan-out lives behind manage_self_provided_lsp_all.
        Do not re-add entries here to make a new import pass — route it through
        providers_api instead.

        Regression note (MA29): this test caught function-level imports in
        _migrate_mcp_ownership_to_scope which bypassed the module-level guard
        by importing providers.services.managed_mcp_registry and
        providers.descriptors.registry directly inside a function. The fix was
        to move that migration into providers (adopt_legacy_mcp_ownership) and
        call it through providers_api. AST walk in _get_imports covers all
        Import/ImportFrom nodes anywhere in the module, not just top-level —
        so this test would catch any future attempt to dodge the boundary with
        function-level imports.
        """
        known_violations: set[str] = set()
        violations = []
        for comp_dir in requester_component_dirs:
            if not comp_dir.exists():
                continue
            for pyfile in _get_python_files(comp_dir):
                for imp in _get_imports(pyfile):
                    # Skip foundation imports — those are allowed
                    if not imp.startswith("audiagentic.components.providers"):
                        continue
                    # Allow only the sanctioned module
                    if not imp.startswith(allowed_providers_prefix):
                        v = (
                            f"{pyfile.relative_to(WORKSPACE_ROOT)}: imports {imp} "
                            f"(allowed: {allowed_providers_prefix} only)"
                        )
                        if v not in known_violations:
                            violations.append(v)

        assert not violations, (
            "Requester component imports providers internals (not the sanctioned API module):\n"
            + "\n".join(violations)
        )

    def test_names_imported_from_providers_api_are_exported(self, requester_component_dirs):
        """Every name a requester imports from providers_api must be in its __all__.

        MA16 locks the provider public API as an exact export list. A name that
        callers import but the module does not publish is a hole in that lock:
        the export matrix cannot be audited against real usage. (RV500 —
        manage_language_servers_all was imported by coding-lsp while absent
        from __all__.)
        """
        import ast

        api_path = (
            WORKSPACE_ROOT / "src" / "audiagentic" / "components" / "providers" / "providers_api.py"
        )
        tree = ast.parse(api_path.read_text(encoding="utf-8"))
        exported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                exported = {
                    el.value
                    for el in node.value.elts  # type: ignore[attr-defined]
                    if isinstance(el, ast.Constant) and isinstance(el.value, str)
                }
        assert exported, "could not parse providers_api.__all__"

        violations = []
        for comp_dir in requester_component_dirs:
            if not comp_dir.exists():
                continue
            for pyfile in _get_python_files(comp_dir):
                node = ast.parse(pyfile.read_text(encoding="utf-8"))
                for stmt in ast.walk(node):
                    if not isinstance(stmt, ast.ImportFrom) or not stmt.module:
                        continue
                    if stmt.module != "audiagentic.components.providers.providers_api":
                        continue
                    for alias in stmt.names:
                        if alias.name != "*" and alias.name not in exported:
                            violations.append(
                                f"{pyfile.relative_to(WORKSPACE_ROOT)}: imports "
                                f"{alias.name!r} from providers_api, which is not in __all__"
                            )

        assert not violations, (
            "Requester imports a providers_api name that is not publicly exported:\n"
            + "\n".join(violations)
        )


class TestProvidersNoReverseImports:
    """RV405 — providers must not import requester domains; handlers are requester-blind."""

    @pytest.fixture
    def providers_dir(self) -> Path:
        return WORKSPACE_ROOT / "src" / "audiagentic" / "components" / "providers"

    def test_no_providers_to_requester_domain_imports(self, providers_dir):
        """Providers imports zero requester domain modules; handlers are requester-blind.

        The MA08 coding-lsp reverse imports are gone: LanguageServerEntry moved to
        providers/contracts, and the lsp-mcp-projection family was deleted once
        managed-mcp superseded it (MA29). Providers import no coding-lsp type.
        """
        forbidden_prefixes = (
            "audiagentic.components.memory",
            "audiagentic.components.coding_lsp",
            "audiagentic.components.planning",
            "audiagentic.components.agent_jobs",
            "audiagentic.components.interaction",
            "audiagentic.components.release",
        )
        violations = []
        for pyfile in _get_python_files(providers_dir):
            for imp in _get_imports(pyfile):
                for prefix in forbidden_prefixes:
                    if imp.startswith(prefix):
                        v = f"{pyfile.relative_to(WORKSPACE_ROOT)}: imports {imp}"
                        violations.append(v)
        assert not violations, (
            "Providers component imports requester domain modules (reverse coupling):\n"
            + "\n".join(violations)
        )


class TestLegacyRecipesZeroConsumers:
    """MA27 preflight: prove legacy recipes module has zero production consumers.

    Once this test passes clean, the legacy services/recipes.py and its
    types (ProviderRecipeRegistry, ProviderCapabilityRecipe, ProviderRecipeKind,
    ProviderRecipeResult, LaunchEnvContributionRecipe) are safe to delete.
    """

    @pytest.fixture
    def src_dir(self) -> Path:
        return WORKSPACE_ROOT / "src" / "audiagentic"

    def test_no_production_import_of_legacy_recipes(self, src_dir):
        """No production code imports providers.services.recipes legacy types."""
        forbidden_module = "audiagentic.components.providers.services.recipes"
        violations = []

        for pyfile in _get_python_files(src_dir):
            # Skip the module itself — it's the one being deleted
            if pyfile.name == "recipes.py" and "providers/services" in str(pyfile):
                continue
            for imp in _get_imports(pyfile):
                if imp == forbidden_module or imp.endswith(".providers.services.recipes"):
                    violations.append(f"{pyfile.relative_to(WORKSPACE_ROOT)}: imports {imp}")

        assert not violations, (
            "Production code still imports legacy recipes module — safe deletion blocked:\n"
            + "\n".join(violations)
        )

    def test_no_legacy_matrix_files(self):
        """Legacy matrix/strategies/recipe_spec files are absent."""
        legacy_names = [
            "hindsight_matrix.yaml",
            "matrix.py",
            "strategies.py",
            "recipe_spec.py",
        ]
        memory_dir = WORKSPACE_ROOT / "src" / "audiagentic" / "components" / "memory"
        found = []

        for name in legacy_names:
            matches = list(memory_dir.rglob(name))
            if matches:
                found.extend(str(m.relative_to(WORKSPACE_ROOT)) for m in matches)

        assert not found, (
            "Legacy matrix/strategy files still exist — safe deletion blocked:\n" + "\n".join(found)
        )

    def test_memory_no_recipe_kind_factory_dispatch(self):
        """Memory component does not dispatch on ProviderRecipeKind or factory."""
        memory_dir = WORKSPACE_ROOT / "src" / "audiagentic" / "components" / "memory"
        forbidden_patterns = [
            "ProviderRecipeKind",
            "ProviderRecipeRegistry",
            "ProviderCapabilityRecipe",
            "ProviderRecipeResult",
            "LaunchEnvContributionRecipe",
        ]
        violations = []

        for pyfile in _get_python_files(memory_dir):
            with open(pyfile, encoding="utf-8") as f:
                source = f.read()
            for pattern in forbidden_patterns:
                if pattern in source:
                    violations.append(f"{pyfile.relative_to(WORKSPACE_ROOT)}: contains {pattern}")

        assert not violations, (
            "Memory still references legacy recipe types — cutover incomplete:\n"
            + "\n".join(violations)
        )
