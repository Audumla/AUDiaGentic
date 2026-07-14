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
            "COMPONENT_" + "PROVIDERS",
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
            # HM21: the managed MCP ownership sync is the sanctioned write
            # path for provider MCP entries — hindsight must use it rather
            # than writing provider configs behind its back.
            "audiagentic.components.providers.services.mcp",
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
            "model_config",
            "hooks",
            "plugin_config",
            "rules",
            "wrapper_cli",
            "context_provider",
            "native_passthrough",
            "launch_env",
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
            has_steps = bool(row.install_steps or row.uninstall_steps or row.status_command)
            if has_steps and row.source_status != "verified":
                violations.append(row.provider_id)
            if row.source_status == "verified" and (not row.source_url or not row.source_date):
                violations.append(f"{row.provider_id}: missing source metadata")
        assert not violations

    def test_unverified_hindsight_installer_refuses_execution(self):
        """Unverified command rows are blocked before subprocess execution."""
        from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
        from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
        from audiagentic.components.memory.hindsight.strategies import build_hindsight_recipe
        from audiagentic.components.providers.services.recipes import ProviderRecipeKind

        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            install_steps=[{"type": "shell", "id": "bad-install", "command": ["definitely-not-real", "--danger"]}],
            source_status="unconfirmed",
            source_url="https://example.invalid",
        )
        recipe = build_hindsight_recipe(
            row,
            HindsightBackendConfig(base_url="https://hindsight.example.com"),
            "test",
        )

        result = recipe.install({})
        assert result.success is False
        assert "refusing to execute" in (result.error or "")

    def test_shell_pipe_hindsight_command_runs_via_shell(self, monkeypatch):
        """Pipe-based installer commands run through a shell for published curl|bash flows."""
        import subprocess

        from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
        from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
        from audiagentic.components.memory.hindsight.strategies import build_hindsight_recipe
        from audiagentic.components.providers.services.recipes import ProviderRecipeKind

        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            install_steps=[{"type": "shell", "id": "pipe-install", "command": "curl -fsSL https://example.invalid/install | bash", "shell": True}],
            source_status="verified",
            source_url="https://example.invalid/docs",
            source_date="2026-06-26",
        )
        recipe = build_hindsight_recipe(
            row,
            HindsightBackendConfig(base_url="https://hindsight.example.com"),
            "test",
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
        from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
        from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
        from audiagentic.components.memory.hindsight.plugin_recipes import PluginConfigRecipe
        from audiagentic.components.providers.services.recipes import ProviderRecipeKind

        row = HindsightRecipeRow(
            provider_id="test",
            display_name="Test",
            integration_type="plugin",
            recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
            install_steps=[],
            uninstall_steps=[],
            source_status="verified",
            source_url="https://example.invalid/docs",
            source_date="2026-06-29",
            audia_action="manage_config_writes",
        )
        recipe = PluginConfigRecipe(
            row,
            HindsightBackendConfig(base_url="https://hindsight.example.com"),
            tmp_path / "opencode.json",
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


class TestRecipeArchitectureGuards:
    """RS19 — recipe architecture and standards guard tests."""

    def test_no_provider_name_branching_in_dispatch(self):
        """Std §2: _RECIPE_FACTORIES keys must be enum values, not string literals.

        Verify no if/elif branches on provider name strings ("cline", "cursor", etc.)
        exist in the strategies module outside of _build_hooks_recipe's explicit
        per-provider specializations (which are documented and allowed).
        """
        strategies_path = (
            WORKSPACE_ROOT
            / "src"
            / "audiagentic"
            / "components"
            / "memory"
            / "hindsight"
            / "strategies.py"
        )
        with open(strategies_path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename="strategies.py")

        # Find _RECIPE_FACTORIES assignment and verify all keys are Name / Attribute nodes
        # (enum member access like ProviderRecipeKind.HOOKS), not string literals.
        factory_keys_ok = True
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_RECIPE_FACTORIES":
                        if isinstance(node.value, ast.Dict):
                            for key in node.value.keys:
                                # Keys must NOT be ast.Constant strings
                                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                    factory_keys_ok = False

        assert factory_keys_ok, (
            "_RECIPE_FACTORIES contains string literal keys — "
            "keys must be ProviderRecipeKind enum values"
        )

        # Verify no top-level if/elif branches on provider name strings in dispatch logic.
        # _build_hooks_recipe has allowed per-provider specialization; check that the
        # main build_hindsight_recipe function does not branch on provider names.
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "build_hindsight_recipe":
                for child in ast.walk(node):
                    if isinstance(child, ast.If):
                        # Check the test expression for string comparisons on provider name
                        test_str = ast.unparse(child.test)
                        forbidden_names = ("cline", "cursor", "codex", "claude", "copilot")
                        for name in forbidden_names:
                            assert name not in test_str.lower(), (
                                f"build_hindsight_recipe branches on provider name '{name}' — "
                                "dispatch must use _RECIPE_FACTORIES keyed by enum"
                            )

    def test_redaction_gate_on_shell_step_results(self):
        """Std §8: ShellStep output must be redacted.

        Create a shell step that outputs a token-like string and assert the result
        does NOT contain the raw token but DOES contain [REDACTED].
        """
        from audiagentic.foundation.steps import ShellStep

        test_token = "sk-aaaaaaaaaaaaaaaaaaaaaaaa"

        # Use a command that echoes the token; run through step to verify redaction.
        # On Windows, use PowerShell-compatible echo.
        step = ShellStep(
            id="test-redact",
            command=(f'echo {test_token}',),
            shell=True,
        )
        result = step.run({})

        # The stdout in outputs should have the token redacted
        stdout = result.outputs.get("stdout", "")
        assert test_token not in stdout, (
            f"ShellStep did not redact token in output: {stdout!r}"
        )
        assert "[REDACTED]" in stdout, (
            f"ShellStep output missing [REDACTED] marker: {stdout!r}"
        )

    def test_factory_completeness(self):
        """Every recipe_kind with matrix rows must have a factory or guidance fallback.

        Read hindsight_matrix.yaml and verify each unique recipe_kind either has an
        entry in _RECIPE_FACTORIES or falls back to _GUIDANCE_SPEC (which covers
        unknown kinds via the .get() + fallback in build_hindsight_recipe).
        """
        import yaml as _yaml

        from audiagentic.components.memory.hindsight.strategies import _RECIPE_FACTORIES
        from audiagentic.components.providers.services.recipes import ProviderRecipeKind

        matrix_path = (
            WORKSPACE_ROOT
            / "src"
            / "audiagentic"
            / "config"
            / "components"
            / "memory"
            / "hindsight_matrix.yaml"
        )
        with open(matrix_path, encoding="utf-8") as f:
            matrix_data = _yaml.safe_load(f)

        # Build enum lookup
        kind_by_value = {k.value: k for k in ProviderRecipeKind}

        missing_uncovered = []
        for row in matrix_data.get("matrix", []):
            raw_kind = row.get("recipe_kind")
            if not raw_kind:
                continue
            kind = kind_by_value.get(raw_kind)
            if kind is None:
                # recipe_kind value doesn't map to a valid enum — this would fail at runtime
                missing_uncovered.append(
                    f"row {row.get('provider_id')}: unknown recipe_kind '{raw_kind}'"
                )
                continue

            has_factory = kind in _RECIPE_FACTORIES
            # The build_hindsight_recipe fallback to _GUIDANCE_SPEC covers all
            # missing keys, so technically every kind is covered. But for explicit
            # traceability, flag kinds that rely on the generic fallback but have
            # no dedicated factory (they'll get guidance-only behavior).
            if not has_factory:
                # Check that the row doesn't have substantive install steps that
                # would need automation — if it does, missing a factory is a gap.
                has_install_steps = bool(row.get("install_steps"))
                if has_install_steps:
                    missing_uncovered.append(
                        f"{row.get('provider_id')}: kind {raw_kind} has install_steps "
                        f"but no factory entry (falls back to guidance-only)"
                    )

        assert not missing_uncovered, (
            "Factory completeness gaps:\n" + "\n".join(missing_uncovered)
        )

    def test_no_stale_path_strings_from_rs_refactors(self):
        """Std §10: No source files should reference old/removed class/function names.

        Check for ManagedEntryRecipe, ConfigEntryTarget, and run_provision /
        run_teardown as code references (not comments/docstrings).
        """
        stale_names = {
            "ManagedEntryRecipe",
            "ConfigEntryTarget",
            "_run_provision",
            "_run_teardown",
            "run_provision",
            "run_teardown",
        }

        src_dir = WORKSPACE_ROOT / "src" / "audiagentic"
        violations = []

        for pyfile in sorted(src_dir.rglob("*.py")):
            try:
                with open(pyfile, encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source, filename=str(pyfile))
            except (SyntaxError, SystemError, RecursionError):
                continue

            rel = pyfile.relative_to(WORKSPACE_ROOT)

            # Check for import references
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(stale in alias.name for stale in stale_names):
                            violations.append(f"{rel}: imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and any(stale in node.module for stale in stale_names):
                        violations.append(f"{rel}: imports from {node.module}")
                    elif node.names:
                        for alias in node.names:
                            if alias.name in stale_names:
                                violations.append(f"{rel}: imports {alias.name}")
                elif isinstance(node, ast.Name) and node.id in stale_names:
                    violations.append(f"{rel}: references {node.id}")

        # Allow known documentation references in recipe_patterns.py docstring
        # (the "SL13 A6" removal note mentions the old names historically).
        filtered = [
            v for v in violations
            if "recipe_patterns.py" not in v or ("imports" in v or "references" in v)
        ]

        assert not filtered, (
            "Stale code references found:\n" + "\n".join(filtered)
        )

    def test_override_allowlist_for_provision_teardown(self):
        """No dependant recipe should reimplement provision() or teardown() without rationale.

        Search for classes that inherit from ProvisioningRecipe and override these
        methods, then check for an allowlisted rationale in the method docstring
        or a preceding comment containing "allow" or "override".
        """
        src_dir = WORKSPACE_ROOT / "src" / "audiagentic"
        violations: list[str] = []

        # Collect all ProvisioningRecipe subclasses and their overridden methods
        for pyfile in sorted(src_dir.rglob("*.py")):
            # Skip the abstract base class itself
            if "recipe_contract.py" in str(pyfile):
                continue

            try:
                with open(pyfile, encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source, filename=str(pyfile))
            except (SyntaxError, SystemError, RecursionError):
                continue

            rel = pyfile.relative_to(WORKSPACE_ROOT)

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                # Check if this class inherits from ProvisioningRecipe (directly or indirectly)
                is_recipe_subclass = False
                for base in node.bases:
                    base_name = ""
                    if isinstance(base, ast.Name):
                        base_name = base.id
                    elif isinstance(base, ast.Attribute):
                        base_name = base.attr

                    # Check known recipe base classes
                    if base_name in (
                        "ProvisioningRecipe",
                        "ProviderCapabilityRecipe",
                        "NoAutomationRecipe",
                        "DeclaredStepRecipe",
                    ):
                        is_recipe_subclass = True
                        break

                if not is_recipe_subclass:
                    continue

                # Check for overridden provision/teardown methods
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name in ("provision", "teardown"):
                        # Get the docstring
                        docstring = ast.get_docstring(item) or ""

                        # Check preceding comments by looking at source lines before the method
                        method_line = item.lineno
                        lines = source.split("\n")
                        preceding_lines = lines[max(0, method_line - 5):method_line - 1]
                        comment_context = "\n".join(preceding_lines).lower()

                        # Check for allowlisted rationale keywords in docstring or comments
                        combined = (docstring + " " + comment_context).lower()
                        has_rationale = any(
                            keyword in combined
                            for keyword in ("allow", "override", "rationale", "reason", "custom")
                        )

                        if not has_rationale:
                            violations.append(
                                f"{rel}:{item.lineno}: {node.name}.{item.name}() overrides without rationale"
                            )

        assert not violations, (
            "Override without allowlisted rationale:\n" + "\n".join(violations)
        )



