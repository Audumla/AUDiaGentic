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
        assert not violations, (
            "foundation/toolchains imports provider modules:\n" + "\n".join(violations)
        )

    def test_no_mcp_specific_helpers_in_config_patcher(self, toolchains_dir):
        """ConfigPatcher must not have add_mcp_entry or remove_mcp_entry methods."""
        config_patcher = toolchains_dir / "config_patcher.py"
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
            "recipe_contract.py docstring leaks component concepts: "
            + ", ".join(violations)
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
            "COMPONENT_PROVIDERS",
            "apply_provider_surfaces",
            "providers.services",
            "surfaces.contributions",
            "hindsight_strategy",
            "build_memory_contributions",
        )
        violations = [term for term in forbidden if term in source]
        assert not violations, (
            "memory_api leaks provider orchestration/surface behavior: "
            + ", ".join(violations)
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
            "audiagentic.components.providers.descriptors.registry",
            "audiagentic.components.providers.services.recipes",
        }
        violations = []
        for pyfile in _get_python_files(memory_dir / "hindsight"):
            for imp in _get_imports(pyfile):
                if imp.startswith("audiagentic.components.providers") and imp not in allowed:
                    violations.append(f"{pyfile.relative_to(WORKSPACE_ROOT)}: imports {imp}")
        assert not violations


class TestProviderRecipeTests:
    """Test provider recipe model types and registry."""

    def test_provider_recipe_kind_enum(self):
        """ProviderRecipeKind enum has expected values."""
        from audiagentic.components.providers.services.recipes import ProviderRecipeKind

        expected = {
            "command_installer",
            "mcp_config",
            "hooks",
            "plugin_config",
            "rules",
            "wrapper_cli",
            "context_provider",
            "native_passthrough",
            "hybrid",
            "guidance_only",
        }
        actual = {k.value for k in ProviderRecipeKind}
        assert actual == expected, f"Expected {expected}, got {actual}"

    def test_provider_recipe_result_ok(self):
        """ProviderRecipeResult.ok creates expected result."""
        from audiagentic.components.providers.services.recipes import (
            ProviderRecipeResult,
            RecipeState,
        )

        result = ProviderRecipeResult.ok(
            RecipeState.VERIFIED,
            artifacts=["art1", "art2"],
            status="done",
            source_url="https://example.com",
            source_date="2025-01-01",
            action_needed="",
        )
        assert result.success is True
        assert result.state is RecipeState.VERIFIED
        assert result.artifacts_owned == ["art1", "art2"]
        assert result.status == "done"
        assert result.source_url == "https://example.com"
        assert result.source_date == "2025-01-01"

    def test_provider_recipe_result_fail(self):
        """ProviderRecipeResult.fail creates expected result."""
        from audiagentic.components.providers.services.recipes import (
            ProviderRecipeResult,
            RecipeState,
        )

        result = ProviderRecipeResult.fail(
            "something broke",
            source_url="https://example.com",
            action_needed="check logs",
        )
        assert result.success is False
        assert result.state is RecipeState.ERROR
        assert result.error == "something broke"
        assert result.source_url == "https://example.com"
        assert result.action_needed == "check logs"

    def test_provider_recipe_registry_register_get(self):
        """ProviderRecipeRegistry can register and retrieve recipes."""
        from audiagentic.components.providers.services.recipes import (
            ProviderRecipeKind,
            ProviderRecipeRegistry,
            ProviderRecipeResult,
            RecipeState,
        )

        class FakeRecipe:
            provider_id = "test"
            capability_id = "hindsight"
            backend_id = None
            recipe_kind = ProviderRecipeKind.MCP_CONFIG

            def probe(self, ctx):
                return ProviderRecipeResult.ok(RecipeState.ABSENT, status="not installed")

        registry = ProviderRecipeRegistry()
        recipe = FakeRecipe()
        registry.register(recipe)

        found = registry.get("test", "hindsight")
        assert found is recipe

    def test_provider_recipe_registry_list_for_provider(self):
        """ProviderRecipeRegistry.list_for_provider filters correctly."""
        from audiagentic.components.providers.services.recipes import (
            ProviderRecipeKind,
            ProviderRecipeRegistry,
            ProviderRecipeResult,
            RecipeState,
        )

        class FakeRecipe:
            def __init__(self, pid, cid):
                self.provider_id = pid
                self.capability_id = cid
                self.backend_id = None
                self.recipe_kind = ProviderRecipeKind.HYBRID

            def probe(self, ctx):
                return ProviderRecipeResult.ok(RecipeState.ABSENT)

        registry = ProviderRecipeRegistry()
        registry.register(FakeRecipe("a", "hindsight"))
        registry.register(FakeRecipe("a", "lsp"))
        registry.register(FakeRecipe("b", "hindsight"))

        results = registry.list_for_provider("a")
        assert len(results) == 2

        results = registry.list_for_provider("a", "hindsight")
        assert len(results) == 1

    def test_hindsight_matrix_has_rows(self):
        """Hindsight recipe matrix has expected providers."""
        from audiagentic.components.memory.hindsight.matrix import (
            get_matrix_rows,
        )

        rows = get_matrix_rows()
        assert len(rows) >= 4, "Matrix should have at least 4 provider rows"

        provider_ids = {row.provider_id for row in rows}
        assert "codex" in provider_ids
        assert "claude" in provider_ids
        assert "copilot" in provider_ids

    def test_hindsight_matrix_by_kind(self):
        """Hindsight recipe matrix can be filtered by kind."""
        from audiagentic.components.memory.hindsight.matrix import (
            ProviderRecipeKind,
            get_rows_by_kind,
        )

        mcp_rows = get_rows_by_kind(ProviderRecipeKind.MCP_CONFIG)
        assert len(mcp_rows) >= 1

        hybrid_rows = get_rows_by_kind(ProviderRecipeKind.HYBRID)
        assert len(hybrid_rows) >= 1

    def test_hindsight_matrix_source_gate(self):
        """Executable installer commands require verified source metadata."""
        from audiagentic.components.memory.hindsight.matrix import (
            get_matrix_rows,
        )

        violations = []
        for row in get_matrix_rows():
            has_command = bool(row.install_command or row.uninstall_command or row.status_command)
            if has_command and row.source_status != "verified":
                violations.append(row.provider_id)
            if row.source_status == "verified" and (not row.source_url or not row.source_date):
                violations.append(f"{row.provider_id}: missing source metadata")
        assert not violations

    def test_unverified_hindsight_installer_refuses_execution(self):
        """Unverified command rows are blocked before subprocess execution."""
        from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
        from audiagentic.components.memory.hindsight.recipes import HooksInstallerRecipe
        from audiagentic.components.memory.hindsight_export import HindsightBackendConfig
        from audiagentic.components.providers.services.recipes import ProviderRecipeKind

        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            install_command="definitely-not-real --danger",
            source_status="unconfirmed",
            source_url="https://example.invalid",
        )
        recipe = HooksInstallerRecipe(
            row,
            HindsightBackendConfig(base_url="https://hindsight.example.com"),
        )

        result = recipe.install({})
        assert result.success is False
        assert "refusing to execute" in (result.error or "")

    def test_shell_pipe_hindsight_command_runs_via_shell(self, monkeypatch):
        """Pipe-based installer commands run through a shell for published curl|bash flows."""
        import subprocess

        from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
        from audiagentic.components.memory.hindsight.recipes import HooksInstallerRecipe
        from audiagentic.components.memory.hindsight_export import HindsightBackendConfig
        from audiagentic.components.providers.services.recipes import ProviderRecipeKind

        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            install_command="curl -fsSL https://example.invalid/install | bash",
            source_status="verified",
            source_url="https://example.invalid/docs",
            source_date="2026-06-26",
        )
        recipe = HooksInstallerRecipe(
            row,
            HindsightBackendConfig(base_url="https://hindsight.example.com"),
        )

        def fake_run(command, **kwargs):
            assert command == "curl -fsSL https://example.invalid/install | bash"
            assert kwargs["shell"] is True
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = recipe.install({})
        assert result.success is True

    def test_plugin_config_recipe_skips_manual_instruction_commands(self, tmp_path):
        """manage_config_writes rows should not try to shell-exec prose install instructions."""
        from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
        from audiagentic.components.memory.hindsight.mcp_recipe import HindsightTarget
        from audiagentic.components.memory.hindsight.recipes import PluginConfigRecipe
        from audiagentic.components.memory.hindsight_export import HindsightBackendConfig
        from audiagentic.components.providers.services.recipes import ProviderRecipeKind

        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="plugin",
            recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
            install_command='Add "@vectorize-io/opencode-hindsight" to plugin array in opencode.json',
            uninstall_command="Remove plugin from opencode.json plugin array",
            source_status="verified",
            source_url="https://example.invalid/docs",
            source_date="2026-06-29",
            audia_action="manage_config_writes",
        )
        recipe = PluginConfigRecipe(
            row,
            HindsightBackendConfig(base_url="https://hindsight.example.com"),
            HindsightTarget(tmp_path / "opencode.json"),
        )

        installed = recipe.install({})
        removed = recipe.uninstall({})
        assert installed.success is True
        assert removed.success is True

    def test_no_hindsight_modules_in_providers_services(self):
        """Providers expose generic recipe seams only; no Hindsight-specific modules."""
        services_dir = WORKSPACE_ROOT / "src" / "audiagentic" / "components" / "providers" / "services"
        violations = [
            path.relative_to(WORKSPACE_ROOT).as_posix()
            for path in services_dir.glob("hindsight*.py")
        ]
        assert not violations

    def test_lsp_recipe_adapter(self):
        """LspRecipeAdapter maps descriptor fields to recipe concepts."""
        from audiagentic.components.providers.services.lsp_recipes import (
            LspRecipeAdapter,
            map_lsp_fields_to_recipe_concepts,
        )

        # Test mapping function
        mapping = map_lsp_fields_to_recipe_concepts(
            provider_id="test",
            has_on_lsp_enabled=True,
            receive_lsp_mcp=True,
            has_language_servers_config=True,
        )
        assert mapping["dominant_strategy"] == "native_passthrough"

        # Test adapter with mock descriptor
        class MockDescriptor:
            provider_id = "test"
            display_name = "Test Provider"
            receive_lsp_mcp = True
            language_servers_config = None

            @staticmethod
            def on_lsp_enabled(project_root):
                return {}

        adapter = LspRecipeAdapter.from_descriptor(MockDescriptor())
        assert adapter.has_native_lsp is True
        assert adapter.recipe_kind.value == "native_passthrough"
