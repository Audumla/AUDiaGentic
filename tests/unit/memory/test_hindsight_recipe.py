from __future__ import annotations

import audiagentic.components.providers  # noqa: F401  (register provider descriptors)
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import (
    HindsightRecipeRow,
    get_matrix_rows,
)
from audiagentic.components.memory.hindsight.mcp_recipe import (
    HindsightMcpRecipe,
    HindsightTarget,
    build_hindsight_entry,
)
from audiagentic.components.memory.hindsight.recipes import (
    RulesOnlyRecipe,
    apply_hindsight,
    build_hindsight_recipe,
    teardown_hindsight,
)
from audiagentic.components.providers.services.recipes import ProviderRecipeKind
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.toolchains.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.config_reader import load_config
from audiagentic.foundation.toolchains.recipe_contract import RecipeState


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


def test_provision_writes_mcp_entry(tmp_path):
    cfg = tmp_path / "mcp.json"
    recipe = HindsightMcpRecipe(_backend(), HindsightTarget(cfg))

    result = recipe.provision({})
    assert result.success
    assert result.state is RecipeState.VERIFIED
    data = load_config(cfg)
    assert data["mcpServers"]["hindsight"]["url"] == "https://hs.example.com/mcp"


def test_provision_idempotent(tmp_path):
    cfg = tmp_path / "mcp.json"
    recipe = HindsightMcpRecipe(_backend(), HindsightTarget(cfg))
    recipe.provision({})
    second = recipe.provision({})
    assert second.success
    # still exactly one entry
    assert list(load_config(cfg)["mcpServers"]) == ["hindsight"]


def test_custom_container_key(tmp_path):
    cfg = tmp_path / "settings.json"
    recipe = HindsightMcpRecipe(
        _backend(), HindsightTarget(cfg, container=("mcp", "servers"))
    )
    recipe.provision({})
    assert "hindsight" in load_config(cfg)["mcp"]["servers"]


def test_teardown_removes_entry(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text('{"mcpServers": {"other": {"url": "x"}}}', encoding="utf-8")
    recipe = HindsightMcpRecipe(_backend(), HindsightTarget(cfg))

    recipe.provision({})
    result = recipe.teardown({})
    assert result.success
    data = load_config(cfg)
    assert "hindsight" not in data["mcpServers"]
    assert "other" in data["mcpServers"]  # user entry preserved


def test_prune_via_registry(tmp_path):
    cfg = tmp_path / "mcp.json"
    registry = ArtifactRegistry(tmp_path)
    recipe = HindsightMcpRecipe(_backend(), HindsightTarget(cfg), registry=registry)

    recipe.provision({})
    assert registry.owned(recipe.recipe_id)["config_keys"]

    result = recipe.prune({})
    assert result.success
    assert "hindsight" not in load_config(cfg).get("mcpServers", {})


def test_switching_backend_url_updates_entry(tmp_path):
    cfg = tmp_path / "mcp.json"
    HindsightMcpRecipe(_backend(), HindsightTarget(cfg)).provision({})
    HindsightMcpRecipe(
        HindsightBackendConfig(base_url="https://new.example.com"), HindsightTarget(cfg)
    ).provision({})
    assert load_config(cfg)["mcpServers"]["hindsight"]["url"] == "https://new.example.com/mcp"


def test_entry_builder_override(tmp_path):
    cfg = tmp_path / "mcp.json"
    recipe = HindsightMcpRecipe(
        _backend(),
        HindsightTarget(cfg),
        entry_builder=lambda b: {"custom": b.base_url},
    )
    recipe.provision({})
    assert load_config(cfg)["mcpServers"]["hindsight"] == {
        "custom": "https://hs.example.com"
    }


def test_provider_writer_callbacks_use_mcp_entries_and_prune(tmp_path):
    """Test that custom writer_fn receives McpServerEntry objects, and probe/prune
    use the callback path correctly."""
    cfg = tmp_path / "provider.toml"
    store: dict[str, McpServerEntry] = {}

    def reader(path):
        return dict(store)

    def writer(path, entries):
        store.clear()
        store.update(entries)
        path.write_text("provider-owned format\n", encoding="utf-8")

    def remover(path, name):
        return store.pop(name, None) is not None

    recipe = HindsightMcpRecipe(
        _backend(api_key="k"),
        HindsightTarget(
            cfg,
            writer_fn=writer,
            reader_fn=reader,
            remover_fn=remover,
        ),
        registry=ArtifactRegistry(tmp_path),
    )

    # Verify configure uses writer_fn with McpServerEntry
    configured = recipe.configure({})
    assert configured.success
    assert "hindsight" in store
    assert store["hindsight"] == McpServerEntry(
        name="hindsight",
        url="https://hs.example.com/mcp",
        headers={"Authorization": "Bearer k"},
        transport="http",
    )

    # Verify probe uses reader_fn and detects entry
    probed = recipe.probe({})
    assert probed.success
    assert probed.state is RecipeState.VERIFIED

    # Verify teardown/prune uses remover_fn
    pruned = recipe.prune({})
    assert pruned.success
    assert "hindsight" not in store


def test_rules_only_recipe_writes_and_removes_rule_block(tmp_path):
    rule_file = tmp_path / "AGENTS.md"
    rule_file.write_text("User rules stay.\n", encoding="utf-8")
    row = HindsightRecipeRow(
        provider_id="test",
        display_name="Test",
        integration_type="rules-only",
        recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
        audia_action="no_source",
    )
    recipe = RulesOnlyRecipe(row, rule_file, project_root=tmp_path)

    result = recipe.configure({})
    assert result.success
    text = rule_file.read_text(encoding="utf-8")
    assert "User rules stay." in text
    assert "audiagentic:hindsight-memory" in text
    assert "Recall before design/history questions" in text

    removed = recipe.prune({})
    assert removed.success
    assert "audiagentic:hindsight-memory" not in rule_file.read_text(encoding="utf-8")
    assert "User rules stay." in rule_file.read_text(encoding="utf-8")


def test_hindsight_orchestration_entrypoints_run_selected_provider(tmp_path, monkeypatch):
    rule_file = tmp_path / "AGENTS.md"
    row = HindsightRecipeRow(
        provider_id="test",
        display_name="Test",
        integration_type="rules-only",
        recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
        audia_action="no_source",
    )

    def fake_register(registry, backend=None, project_root=None):
        recipe = RulesOnlyRecipe(row, rule_file, project_root=project_root)
        registry.register(recipe)
        return [recipe]

    monkeypatch.setattr(
        "audiagentic.components.memory.hindsight.recipes.register_hindsight_recipes",
        fake_register,
    )

    applied = apply_hindsight(tmp_path, backend=_backend(), provider_ids=["test"])
    assert applied["test"].success
    assert "audiagentic:hindsight-memory" in rule_file.read_text(encoding="utf-8")

    torn_down = teardown_hindsight(tmp_path, backend=_backend(), provider_ids=["test"])
    assert torn_down["test"].success
    assert "audiagentic:hindsight-memory" not in rule_file.read_text(encoding="utf-8")


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


def test_mcp_config_adapter_provision_writes_config_via_step_path(tmp_path):
    row = HindsightRecipeRow(
        provider_id="gemini",
        display_name="Gemini",
        integration_type="mcp",
        recipe_kind=ProviderRecipeKind.MCP_CONFIG,
        source_status="verified",
        audia_action="manage_config_writes",
        source_url="https://example.invalid/gemini",
        source_date="2026-07-01",
    )
    recipe = build_hindsight_recipe(row, _backend(api_key="k"), "gemini", tmp_path)

    result = recipe.provision({})

    assert result.success, result.error
    settings = tmp_path / ".gemini" / "settings.json"
    assert "hindsight" in settings.read_text(encoding="utf-8")


def test_hybrid_recipe_provision_steps_include_installer_and_mcp_and_rules(tmp_path):
    row = HindsightRecipeRow(
        provider_id="copilot",
        display_name="GitHub Copilot",
        integration_type="mcp+rules",
        recipe_kind=ProviderRecipeKind.HYBRID,
        source_status="verified",
        audia_action="call_official_installer",
        source_url="https://example.invalid/copilot",
        source_date="2026-07-01",
        install_steps=[
            {
                "type": "shell",
                "id": "copilot-init",
                "command": ["hindsight-copilot", "init", "--api-token={TOKEN}", "--bank-id={ID}"],
            }
        ],
    )
    recipe = build_hindsight_recipe(row, _backend(api_key="k", bank_id="bank"), "copilot", tmp_path)

    steps = recipe.provision_steps()
    ids = [step.id for step in steps]

    assert "copilot-init" in ids
    assert any("mcp" in step_id or "config" in step_id for step_id in ids)
    assert any("rule" in step_id for step_id in ids)


def test_apply_hindsight_mcp_provider_writes_inside_project_root(tmp_path, monkeypatch):
    """Regression: MCP-config provisioning must (a) succeed through the adapter
    path (inner RecipeResult re-stamped, not assumed ProviderRecipeResult) and
    (b) write inside project_root, never relative to the current directory."""
    from audiagentic.components.memory.hindsight.recipes import apply_hindsight

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

    def test_status_includes_source_date_and_source_status(self, tmp_path):
        from audiagentic.components.memory.hindsight.recipes import (
            build_hindsight_recipe,
            build_hindsight_status,
        )
        from audiagentic.components.providers.services.recipes import ProviderRecipeRegistry

        registry = ProviderRecipeRegistry()
        row = HindsightRecipeRow(
            provider_id="gemini",
            display_name="Gemini",
            integration_type="mcp",
            recipe_kind=ProviderRecipeKind.MCP_CONFIG,
            source_status="verified",
            audia_action="manage_config_writes",
            source_url="https://example.invalid/gemini",
            source_date="2026-07-01",
        )
        recipe = build_hindsight_recipe(row, _backend(api_key="k"), "gemini", tmp_path)
        registry.register(recipe)

        # Provision so probe returns VERIFIED
        recipe.provision({})

        status = build_hindsight_status(registry, "gemini")
        assert status["provider_id"] == "gemini"
        hs = status["hindsight"]
        assert hs["status"] == "active"
        recs = hs["recipes"]
        assert len(recs) >= 1

        entry = recs[0]
        # All HM15 fields present
        assert "kind" in entry
        assert "state" in entry
        assert "status" in entry
        assert "action_needed" in entry
        assert "source_url" in entry
        assert "source_date" in entry
        assert "source_status" in entry
        assert "artifacts_owned" in entry
        # Provenance fields populated from matrix row
        assert entry["source_date"] == "2026-07-01"
        assert entry["source_status"] == "verified"
        assert entry["state"] == "verified"

    def test_status_for_unknown_provider(self, tmp_path):
        from audiagentic.components.memory.hindsight.recipes import (
            build_hindsight_status,
        )
        from audiagentic.components.providers.services.recipes import ProviderRecipeRegistry

        registry = ProviderRecipeRegistry()
        status = build_hindsight_status(registry, "no-such-provider")
        assert status["provider_id"] == "no-such-provider"
        assert status["hindsight"]["status"] == "not_registered"

    def test_status_artifacts_owned_present_in_result(self, tmp_path):
        """artifacts_owned field is populated by provision (not probe/status)."""
        from audiagentic.components.memory.hindsight.recipes import build_hindsight_recipe

        row = HindsightRecipeRow(
            provider_id="gemini",
            display_name="Gemini",
            integration_type="mcp",
            recipe_kind=ProviderRecipeKind.MCP_CONFIG,
            source_status="verified",
            audia_action="manage_config_writes",
        )
        recipe = build_hindsight_recipe(row, _backend(api_key="k"), "gemini", tmp_path)

        result = recipe.provision({})
        assert result.success
        # Provision returns artifact IDs; status/probe reads state only.
        assert len(result.artifacts_owned) >= 1


class TestMemoryStatusProviderAgnostic:
    """memory_status must never leak per-provider Hindsight detail."""

    def test_memory_status_no_provider_detail(self, tmp_path):
        from audiagentic.components.memory.memory_api import memory_status

        result = memory_status(tmp_path)
        payload = str(result).lower()
        for kw in ("gemini", "copilot", "claude"):
            assert kw not in payload, f"memory_status must not mention '{kw}'"
