from __future__ import annotations

import audiagentic.components.providers  # noqa: F401  (register provider descriptors)
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.lifecycle import (
    apply_hindsight,
    teardown_hindsight,
)
from audiagentic.components.memory.hindsight.matrix import (
    HindsightRecipeRow,
    get_matrix_rows,
)
from audiagentic.components.memory.hindsight.mcp_recipe import build_hindsight_entry
from audiagentic.components.memory.hindsight.strategies import build_hindsight_recipe
from audiagentic.components.providers.services.recipes import (
    ProviderRecipeKind,
    RecipeState,
)


def _backend(**kw):
    return HindsightBackendConfig(base_url="https://hs.example.com", **kw)


def test_sse_entry_shape():
    entry = build_hindsight_entry(_backend(transport="sse", api_key="k"))
    assert entry["type"] == "sse"
    assert entry["url"] == "https://hs.example.com/mcp"
    assert entry["headers"]["Authorization"] == "Bearer k"


def test_stdio_entry_shape():
    entry = build_hindsight_entry(_backend(transport="stdio", api_key="k"))
    assert entry["command"] == "hindsight-mcp"
    assert "--base-url" in entry["args"]
    assert entry["env"]["HINDSIGHT_API_KEY"] == "k"


def test_managed_block_and_surface_coexistence(tmp_path):
    """Infrastructure test: managed_block and surfaces regions survive each other.

    Retained after SL13 A7 as a safety net for the underlying infrastructure,
    even though hindsight no longer writes blocks directly (flows via surface
    contributions). Pins the coexistence invariant — strip_managed_content only
    strips HTML-comment regions; managed_block uses Markdown #-comments.
    """
    from audiagentic.components.providers.surfaces.base import (
        SurfaceBlock,
        apply_managed_blocks,
    )
    from audiagentic.foundation.toolchains.managed_block import (
        apply_managed_block,
        remove_managed_block,
    )

    rule_file = tmp_path / "AGENTS.md"
    rule_file.write_text("User content.\n", encoding="utf-8")

    surface_block = SurfaceBlock(
        path=rule_file, block_id="provider-surface", content="## Provider note\nSome text."
    )
    existing = rule_file.read_text(encoding="utf-8")
    with_region = apply_managed_blocks(existing, [surface_block])
    rule_file.write_text(with_region, encoding="utf-8")
    assert "<!-- ag:managed:begin -->" in rule_file.read_text(encoding="utf-8")

    change = apply_managed_block(rule_file, "hindsight-memory", "Rule content.")
    assert change.existed is False
    text_after_hindsight = rule_file.read_text(encoding="utf-8")
    assert "audiagentic:hindsight-memory" in text_after_hindsight

    surface_reapply = apply_managed_blocks(text_after_hindsight, [surface_block])
    rule_file.write_text(surface_reapply, encoding="utf-8")
    assert "audiagentic:hindsight-memory" in rule_file.read_text(encoding="utf-8")

    remove_managed_block(rule_file, "hindsight-memory")
    text_after_prune = rule_file.read_text(encoding="utf-8")
    assert "<!-- ag:managed:begin -->" in text_after_prune
    assert "User content." in text_after_prune
    assert "audiagentic:hindsight-memory" not in text_after_prune


def test_hindsight_orchestration_entrypoints_run_selected_provider(tmp_path, monkeypatch):
    """After SL13 A7 and SL15: guidance recipes are assembled via RecipeSpec.

    apply_hindsight and teardown_hindsight succeed with guidance recipes; no file
    writing is expected (content flows via surface contributions).
    """
    from audiagentic.components.memory.hindsight.recipe_spec import (
        ParamBinding,
        RecipeSpec,
        StatusOverride,
        assemble_hindsight_recipe,
    )

    _GUIDANCE_SPEC = RecipeSpec(
        pattern="no_automation",
        params=[ParamBinding(param_name="action_needed", row_field="notes")],
        status_overrides=[StatusOverride(method="probe", state="absent", status_text="no automated integration available")],
    )

    row = HindsightRecipeRow(
        provider_id="test",
        display_name="Test",
        integration_type="rules-only",
        recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
        audia_action="no_source",
    )

    def fake_register(registry, backend=None, project_root=None):
        recipe = assemble_hindsight_recipe(row, None, _GUIDANCE_SPEC)  # type: ignore[arg-type]
        registry.register(recipe)
        return [recipe]

    monkeypatch.setattr(
        "audiagentic.components.memory.hindsight.lifecycle.register_hindsight_recipes",
        fake_register,
    )

    applied = apply_hindsight(tmp_path, backend=_backend(), provider_ids=["test"])
    assert applied["test"].success

    torn_down = teardown_hindsight(tmp_path, backend=_backend(), provider_ids=["test"])
    assert torn_down["test"].success


def test_verified_matrix_step_definitions_build_provision_steps(tmp_path):
    backend = _backend(api_key="sk-test", bank_id="bank")
    automated_kinds = {
        ProviderRecipeKind.HOOKS,
        ProviderRecipeKind.WRAPPER_CLI,
        ProviderRecipeKind.PLUGIN_CONFIG,
        ProviderRecipeKind.MCP_CONFIG,
        ProviderRecipeKind.HYBRID,
    }

    for row in get_matrix_rows():
        if row.source_status != "verified" or row.recipe_kind not in automated_kinds:
            continue
        recipe = build_hindsight_recipe(row, backend, row.provider_id, tmp_path)
        provision_steps = getattr(recipe, "provision_steps", None)
        if not callable(provision_steps):
            continue

        steps = provision_steps()

        if row.install_steps or row.configure_steps:
            assert steps, f"{row.provider_id} has step defs but recipe returned no ProvisionSteps"


def test_apply_hindsight_mcp_provider_writes_inside_project_root(tmp_path, monkeypatch):
    """Regression: MCP-config provisioning must (a) succeed through the adapter
    path (inner RecipeResult re-stamped, not assumed ProviderRecipeResult) and
    (b) write inside project_root, never relative to the current directory."""
    from audiagentic.components.memory.hindsight.lifecycle import apply_hindsight

    # Run from an unrelated cwd to prove paths anchor to project_root, not cwd.
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)

    project = tmp_path / "project"
    project.mkdir()

    # gemini is a verified MCP-config provider writing .gemini/settings.json.
    results = apply_hindsight(project, backend=_backend(api_key="k"), provider_ids=["gemini"])

    res = results["gemini"]
    assert res.success, res.error           # Bug A: adapter path must not raise
    settings = project / ".gemini" / "settings.json"
    assert settings.exists()                 # Bug B: written under project_root
    assert "hindsight" in settings.read_text(encoding="utf-8")
    # Nothing leaked into the working directory.
    assert not (other / ".gemini").exists()


class TestBuildHindsightStatus:
    """HM15: status output includes source freshness, artifacts, and provenance."""

    def test_status_for_unknown_provider(self, tmp_path):
        from audiagentic.components.memory.hindsight.status import build_hindsight_status
        from audiagentic.components.providers.services.recipes import ProviderRecipeRegistry

        registry = ProviderRecipeRegistry()
        status = build_hindsight_status(registry, "no-such-provider")
        assert status["provider_id"] == "no-such-provider"
        assert status["hindsight"]["status"] == "not_registered"

class TestMemoryStatusProviderAgnostic:
    """memory_status must never leak per-provider Hindsight detail."""

    def test_memory_status_no_provider_detail(self, tmp_path):
        from audiagentic.components.memory.memory_api import memory_status

        result = memory_status(tmp_path)
        payload = str(result).lower()
        for kw in ("gemini", "copilot", "claude"):
            assert kw not in payload, f"memory_status must not mention '{kw}'"


def test_row_recipe_stamp_matches_provider_recipe_result_shape():
    """_RowRecipe._stamp produces a ProviderRecipeResult with correct provenance fields.

    Verifies that source_url/source_date come from the row and action_needed
    falls back to row.audia_action when the input result carries none.
    """
    from audiagentic.components.memory.hindsight.recipes import _RowRecipe
    from audiagentic.components.providers.services.recipes import (
        ProviderRecipeResult,
        RecipeResult,
        RecipeState,
    )

    row = HindsightRecipeRow(
        provider_id="test-stamp",
        display_name="Test Stamp",
        integration_type="guidance",
        recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
        source_url="https://example.invalid/stamp-test",
        source_date="2026-06-15",
        audia_action="call_official_installer",
    )

    class _MinimalStampRecipe(_RowRecipe):
        def probe(self, context):  # noqa: ANN001,ANN202
            return RecipeResult.ok(RecipeState.ABSENT)

        def install(self, context):  # noqa: ANN001,ANN202
            return RecipeResult.ok(RecipeState.INSTALLING)

        def configure(self, context):  # noqa: ANN001,ANN202
            return RecipeResult.ok(RecipeState.CONFIGURING)

        def verify(self, context):  # noqa: ANN001,ANN202
            return RecipeResult.ok(RecipeState.VERIFIED)

        def uninstall(self, context):  # noqa: ANN001,ANN202
            return RecipeResult.ok(RecipeState.ABSENT)

        def prune(self, context):  # noqa: ANN001,ANN202
            return RecipeResult.ok(RecipeState.ABSENT)

    recipe = _MinimalStampRecipe(row)

    # Case 1: result has no action_needed -> falls back to row.audia_action
    base_result = RecipeResult.ok(RecipeState.VERIFIED, status="ok")
    stamped = recipe._stamp(base_result)

    assert isinstance(stamped, ProviderRecipeResult)
    assert stamped.source_url == "https://example.invalid/stamp-test"
    assert stamped.source_date == "2026-06-15"
    assert stamped.action_needed == "call_official_installer", (
        f"action_needed should fall back to row.audia_action, got {stamped.action_needed!r}"
    )

    # Case 2: result has action_needed set -> preserves it over audia_action
    base_with_action = RecipeResult.ok(
        RecipeState.VERIFIED, action_needed="custom guidance"
    )
    stamped2 = recipe._stamp(base_with_action)

    assert stamped2.action_needed == "custom guidance", (
        f"action_needed from result should override audia_action, got {stamped2.action_needed!r}"
    )


class TestPluginConfigSourceGate:
    """RS11: Plugin config/plugin_url_config install/uninstall refuse unverified source."""

    def _make_unverified_plugin_config_row(self, **kw):
        return HindsightRecipeRow(
            provider_id="test-unverified-plugin",
            display_name="Test Unverified Plugin",
            integration_type="plugin-config",
            recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
            source_status="unconfirmed",
            audia_action="call_official_installer",
            install_steps=[{"type": "shell", "id": "install-step", "command": ["echo", "test"]}],
            uninstall_steps=[{"type": "shell", "id": "uninstall-step", "command": ["echo", "rm"]}],
            notes="manual installation required",
            **kw,
        )

    def test_plugin_config_install_refuses_unverified_source(self):
        from audiagentic.components.memory.hindsight.plugin_recipes import PluginConfigRecipe

        row = self._make_unverified_plugin_config_row()
        recipe = PluginConfigRecipe(row, _backend())
        result = recipe.install({})
        assert result.success is False
        assert result.action_needed == "manual installation required"

    def test_plugin_config_uninstall_refuses_unverified_source(self):
        from audiagentic.components.memory.hindsight.plugin_recipes import PluginConfigRecipe

        row = self._make_unverified_plugin_config_row()
        recipe = PluginConfigRecipe(row, _backend())
        result = recipe.uninstall({})
        assert result.state is RecipeState.ABSENT
        assert result.action_needed == "manual installation required"

    def test_plugin_url_config_install_refuses_unverified_source(self, tmp_path):
        from audiagentic.components.memory.hindsight.plugin_recipes import _PluginUrlConfigRecipe

        row = self._make_unverified_plugin_config_row()
        config_path = tmp_path / "test-config.json"
        recipe = _PluginUrlConfigRecipe(row, _backend(), config_path)
        result = recipe.install({})
        assert result.success is False
        assert result.action_needed == "manual installation required"

    def test_plugin_url_config_uninstall_refuses_unverified_source(self, tmp_path):
        from audiagentic.components.memory.hindsight.plugin_recipes import _PluginUrlConfigRecipe

        row = self._make_unverified_plugin_config_row()
        config_path = tmp_path / "test-config.json"
        recipe = _PluginUrlConfigRecipe(row, _backend(), config_path)
        result = recipe.uninstall({})
        assert result.state is RecipeState.ABSENT
        assert result.action_needed == "manual installation required"


class TestShouldRunPluginCommand:
    """_should_run_plugin_command (module-level) returns True iff audia_action == 'call_official_installer'."""

    def test_plugin_config_should_run_true(self):
        from audiagentic.components.memory.hindsight.plugin_recipes import (
            PluginConfigRecipe,
            _should_run_plugin_command,
        )

        row = HindsightRecipeRow(
            provider_id="test-srpc",
            display_name="Test SRPC",
            integration_type="plugin-config",
            recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
            source_status="verified",
            audia_action="call_official_installer",
        )
        recipe = PluginConfigRecipe(row, _backend())
        assert _should_run_plugin_command(recipe._row) is True

    def test_plugin_config_should_run_false(self):
        from audiagentic.components.memory.hindsight.plugin_recipes import (
            PluginConfigRecipe,
            _should_run_plugin_command,
        )

        row = HindsightRecipeRow(
            provider_id="test-srpc",
            display_name="Test SRPC",
            integration_type="plugin-config",
            recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
            source_status="verified",
            audia_action="manage_config_writes",
        )
        recipe = PluginConfigRecipe(row, _backend())
        assert _should_run_plugin_command(recipe._row) is False

    def test_plugin_url_config_should_run_true(self, tmp_path):
        from audiagentic.components.memory.hindsight.plugin_recipes import (
            _PluginUrlConfigRecipe,
            _should_run_plugin_command,
        )

        row = HindsightRecipeRow(
            provider_id="test-srpc-url",
            display_name="Test SRPC URL",
            integration_type="plugin-config",
            recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
            source_status="verified",
            audia_action="call_official_installer",
        )
        recipe = _PluginUrlConfigRecipe(row, _backend(), tmp_path / "cfg.json")
        assert _should_run_plugin_command(recipe._row) is True

    def test_plugin_url_config_should_run_false(self, tmp_path):
        from audiagentic.components.memory.hindsight.plugin_recipes import (
            _PluginUrlConfigRecipe,
            _should_run_plugin_command,
        )

        row = HindsightRecipeRow(
            provider_id="test-srpc-url",
            display_name="Test SRPC URL",
            integration_type="plugin-config",
            recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
            source_status="verified",
            audia_action="manage_config_writes",
        )
        recipe = _PluginUrlConfigRecipe(row, _backend(), tmp_path / "cfg.json")
        assert _should_run_plugin_command(recipe._row) is False


class TestPluginUrlConfigRoundTrip:
    """RS18: configure → prune round-trip correctness."""

    def test_configure_writes_url_config_file(self, tmp_path):
        from audiagentic.components.memory.hindsight.plugin_recipes import (
            _PluginUrlConfigRecipe,
        )

        row = HindsightRecipeRow(
            provider_id="test-roundtrip",
            display_name="Test RoundTrip",
            integration_type="plugin-config",
            recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
            source_status="verified",
            audia_action="manage_config_writes",
        )
        config_path = tmp_path / "hindsight" / "test-roundtrip.json"
        backend = _backend(api_key="sk-test", bank_id="mybank")
        recipe = _PluginUrlConfigRecipe(row, backend, config_path)

        result = recipe.configure({})
        assert result.success
        assert result.state is RecipeState.CONFIGURING
        assert config_path.exists()

        import json

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["hindsightApiUrl"] == "https://hs.example.com"
        assert data["hindsightApiToken"] == "sk-test"
        assert data["bankId"] == "mybank"

    def test_prune_removes_only_target_file(self, tmp_path):
        from audiagentic.components.memory.hindsight.plugin_recipes import (
            _PluginUrlConfigRecipe,
        )

        row = HindsightRecipeRow(
            provider_id="test-prune",
            display_name="Test Prune",
            integration_type="plugin-config",
            recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
            source_status="verified",
            audia_action="manage_config_writes",
        )
        config_path = tmp_path / "hindsight" / "test-prune.json"
        sibling = tmp_path / "hindsight" / "other-file.txt"

        backend = _backend(api_key="sk-test")
        recipe = _PluginUrlConfigRecipe(row, backend, config_path)

        recipe.configure({})
        sibling.write_text("unrelated data", encoding="utf-8")
        assert config_path.exists()
        assert sibling.exists()

        result = recipe.prune({})
        assert result.success
        assert result.state is RecipeState.ABSENT
        assert not config_path.exists(), "target file should be removed"
        assert sibling.exists(), "sibling file must survive prune"

    def test_prune_tolerates_missing_file(self, tmp_path):
        from audiagentic.components.memory.hindsight.plugin_recipes import (
            _PluginUrlConfigRecipe,
        )

        row = HindsightRecipeRow(
            provider_id="test-prune-missing",
            display_name="Test Prune Missing",
            integration_type="plugin-config",
            recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
            source_status="verified",
            audia_action="manage_config_writes",
        )
        config_path = tmp_path / "hindsight" / "nonexistent.json"
        backend = _backend()
        recipe = _PluginUrlConfigRecipe(row, backend, config_path)

        result = recipe.prune({})
        assert result.success
        assert result.state is RecipeState.ABSENT


class TestCodexConfigureUsesWriteFileStep:
    """RS18: Codex configure routes writes through WriteFileStep."""

    def test_configure_writes_via_write_file_step(self, tmp_path, monkeypatch):
        from audiagentic.components.memory.hindsight.codex_recipe import (
            CodexHindsightRecipe,
        )

        row = HindsightRecipeRow(
            provider_id="codex",
            display_name="Codex",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            source_status="verified",
            audia_action="manage_config_writes",
        )
        backend = _backend(api_key="sk-test", bank_id="codex")
        monkeypatch.setattr("audiagentic.components.memory.hindsight.codex_recipe._home", lambda: tmp_path)  # noqa: ARG005
        recipe = CodexHindsightRecipe(row, backend)

        result = recipe.configure({})
        assert result.success
        assert result.state is RecipeState.CONFIGURING

        user_config = tmp_path / ".hindsight" / "codex.json"
        hooks_file = tmp_path / ".codex" / "hooks.json"
        assert user_config.exists()
        assert hooks_file.exists()

        import json

        data = json.loads(user_config.read_text(encoding="utf-8"))
        assert data["hindsightApiUrl"] == "https://hs.example.com"


class TestPiConfigureIntentionalOneOff:
    """RS18: Pi configure uses bare write_text (intentional one-off due to literal
    brace placeholders like "{project}" that conflict with WriteFileStep substitution)."""

    def test_configure_writes_config_correctly(self, tmp_path, monkeypatch):
        from audiagentic.components.memory.hindsight.pi_recipe import (
            PiHindsightRecipe,
        )

        row = HindsightRecipeRow(
            provider_id="pi",
            display_name="Pi",
            integration_type="hooks",
            recipe_kind=ProviderRecipeKind.HOOKS,
            source_status="verified",
            audia_action="manage_config_writes",
        )
        backend = _backend(api_key="sk-test", bank_id="audiagentic")
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)  # noqa: ARG005
        recipe = PiHindsightRecipe(row, backend)

        result = recipe.configure({})
        assert result.success
        assert result.state is RecipeState.CONFIGURING

        config_path = tmp_path / ".hindsight" / "config.json"
        assert config_path.exists()

        import json

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["baseUrl"] == "https://hs.example.com"
        assert data.get("host", {}).get("pi", {}).get("enabled") is True
        # Literal brace placeholders survive correctly
        pi_data = data.get("host", {}).get("pi", {})
        assert "{project}" in pi_data.get("autoRecallTags", [])
