from __future__ import annotations

from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
from audiagentic.components.memory.hindsight.mcp_recipe import (
    HindsightMcpRecipe,
    HindsightTarget,
    build_hindsight_entry,
)
from audiagentic.components.memory.hindsight.recipes import (
    RulesOnlyRecipe,
    apply_hindsight,
    teardown_hindsight,
)
from audiagentic.components.memory.hindsight_export import HindsightBackendConfig
from audiagentic.components.providers.services.recipes import ProviderRecipeKind
from audiagentic.foundation.toolchains.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.config_reader import load_config
from audiagentic.foundation.toolchains.recipe_contract import RecipeState


def _backend(**kw):
    return HindsightBackendConfig(base_url="https://hs.example.com", **kw)


def test_sse_entry_shape():
    entry = build_hindsight_entry(_backend(transport="sse", api_key="k"))
    assert entry["type"] == "sse"
    assert entry["url"] == "https://hs.example.com"
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
    assert data["mcpServers"]["hindsight"]["url"] == "https://hs.example.com"


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
    assert load_config(cfg)["mcpServers"]["hindsight"]["url"] == "https://new.example.com"


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
