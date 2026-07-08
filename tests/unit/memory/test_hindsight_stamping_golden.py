"""Golden snapshot of hindsight recipe stamped output (SL11 regression guard).

Pins the provenance-stamped fields (success/state/status/source_url/
source_date/action_needed) of every recipe class's probe() and dry_run(), plus
a couple of full lifecycle results, so the per-method-stamping strip in SL11 is
provably behaviour-preserving. If a value here changes, the strip altered
observable behaviour and must be reviewed — not blindly re-baselined.
"""
from __future__ import annotations

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
from audiagentic.components.memory.hindsight.plugin_recipes import (
    PluginConfigRecipe,
    _PluginArrayRecipe,
    _PluginUrlConfigRecipe,
)
from audiagentic.components.memory.hindsight.recipes import (
    GuidanceOnlyRecipe,
    HooksInstallerRecipe,
    _McpConfigAdapter,
)
from audiagentic.components.providers.services.recipes import ProviderRecipeKind


def _backend(**kw):
    return HindsightBackendConfig(base_url="https://hs.example.com", **kw)


def _row(**kw) -> HindsightRecipeRow:
    base = dict(
        provider_id="golden",
        display_name="Golden",
        integration_type="test",
        recipe_kind=ProviderRecipeKind.MCP_CONFIG,
        source_status="verified",
        source_url="https://src.example/doc",
        source_date="2026-01-01",
        audia_action="manage_config_writes",
    )
    base.update(kw)
    return HindsightRecipeRow(**base)


def _snap(result) -> dict:
    return {
        "success": result.success,
        "state": result.state.value,
        "status": result.status,
        "source_url": result.source_url,
        "source_date": result.source_date,
        "action_needed": result.action_needed,
    }


def test_hooks_probe_and_dry_run_golden():
    r = HooksInstallerRecipe(
        _row(recipe_kind=ProviderRecipeKind.HOOKS, status_command=""), _backend()
    )
    assert _snap(r.probe({})) == {
        "success": True,
        "state": "absent",
        "status": "no status probe available",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manage_config_writes",
    }
    assert _snap(r.dry_run({})) == {
        "success": True,
        "state": "absent",
        "status": "no install steps (dry-run)",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manage_config_writes",
    }


def test_hooks_unverified_probe_golden():
    r = HooksInstallerRecipe(
        _row(recipe_kind=ProviderRecipeKind.HOOKS, source_status="unconfirmed", notes="do X"),
        _backend(),
    )
    assert _snap(r.probe({})) == {
        "success": True,
        "state": "absent",
        "status": "source unconfirmed; installer blocked",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "do X",
    }


def test_plugin_config_probe_dry_run_golden():
    r = PluginConfigRecipe(_row(recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG), _backend())
    assert _snap(r.probe({})) == {
        "success": True,
        "state": "absent",
        "status": "plugin config managed by CLI",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manage_config_writes",
    }
    assert _snap(r.dry_run({})) == {
        "success": True,
        "state": "absent",
        "status": "would install plugin (dry-run)",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manage_config_writes",
    }


def test_plugin_url_config_probe_golden(tmp_path):
    r = _PluginUrlConfigRecipe(
        _row(recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG),
        _backend(),
        tmp_path / "url.json",
    )
    assert _snap(r.probe({})) == {
        "success": True,
        "state": "absent",
        "status": "plugin URL config absent or stale",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manage_config_writes",
    }


def test_plugin_array_probe_golden(tmp_path):
    r = _PluginArrayRecipe(
        _row(recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG),
        _backend(),
        tmp_path / "arr.json",
    )
    assert _snap(r.probe({})) == {
        "success": True,
        "state": "absent",
        "status": "no reader configured for plugin array",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manage_config_writes",
    }


def test_guidance_only_probe_provision_golden():
    r = GuidanceOnlyRecipe(_row(source_status="unconfirmed", notes="manual note"))
    assert _snap(r.probe({})) == {
        "success": True,
        "state": "absent",
        "status": "no automated integration available",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manual note",
    }
    assert _snap(r.provision({})) == {
        "success": True,
        "state": "absent",
        "status": "skipped: no automated Hindsight integration for this provider",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manual note",
    }


def test_mcp_config_adapter_probe_golden(tmp_path):
    r = _McpConfigAdapter(
        _row(), _backend(), tmp_path / "mcp.json", project_root=tmp_path,
    )
    assert _snap(r.probe({})) == {
        "success": True,
        "state": "absent",
        "status": "entry absent",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manage_config_writes",
    }
    assert _snap(r.dry_run({})) == {
        "success": True,
        "state": "absent",
        "status": "would install (dry-run)",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manage_config_writes",
    }


def test_hybrid_collapsed_to_mcp_adapter(tmp_path):
    """After SL13 A8: HYBRID maps to _McpConfigAdapter (rules via surfaces).

    _CompositeRecipe has been deleted; the HYBRID kind uses the same MCP adapter
    and rules content flows through surface contributions (memory.yaml).
    """
    r = _McpConfigAdapter(
        _row(recipe_kind=ProviderRecipeKind.HYBRID),
        _backend(),
        tmp_path / "mcp.json",
        project_root=tmp_path,
    )
    snap = _snap(r.probe({}))
    assert snap["success"] is True
    assert snap["state"] == "absent"
    assert snap["source_url"] == "https://src.example/doc"
    assert snap["action_needed"] == "manage_config_writes"
