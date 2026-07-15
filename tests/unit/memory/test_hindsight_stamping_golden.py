"""Golden snapshot of hindsight recipe stamped output (SL11 regression guard).

Pins the provenance-stamped fields (success/state/status/source_url/
source_date/action_needed) of every recipe class's probe() and dry_run(), plus
a couple of full lifecycle results, so the per-method-stamping strip in SL11 is
provably behaviour-preserving. If a value here changes, the strip altered
observable behaviour and must be reviewed — not blindly re-baselined.

After SL15: GuidanceOnlyRecipe and HooksInstallerRecipe classes are replaced
by config-driven assembly via RecipeSpec; goldens assert the same behaviour.
"""
from __future__ import annotations

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
from audiagentic.components.memory.hindsight.plugin_definition import (
    HindsightPluginDefinition,
    HindsightPluginDesired,
)
from audiagentic.components.memory.hindsight.plugin_recipes import (
    PluginConfigRecipe,
    _PluginArrayRecipe,
    _PluginUrlConfigRecipe,
    _repair_windows_plugin_mcp,
)
from audiagentic.components.memory.hindsight.recipe_spec import (
    ParamBinding,
    RecipeSpec,
    StatusOverride,
    assemble_hindsight_recipe,
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


#: Spec for guidance-only golden tests (matches strategies._GUIDANCE_SPEC).
_GUIDANCE_ONLY_SPEC = RecipeSpec(
    pattern="no_automation",
    params=[
        ParamBinding(param_name="action_needed", row_field="notes"),
        ParamBinding(param_name="skip_status", literal="skipped: no automated Hindsight integration for this provider"),
    ],
    status_overrides=[
        StatusOverride(method="probe", state="absent", status_text="no automated integration available"),
    ],
)

#: Spec for hooks installer golden tests (matches strategies._HOOKS_SPEC).
_HOOKS_SPEC = RecipeSpec(
    pattern="declared_step",
    params=[
        ParamBinding(param_name="install_steps", row_field="install_steps"),
        ParamBinding(param_name="uninstall_steps", row_field="uninstall_steps"),
        ParamBinding(param_name="status_command", row_field="status_command"),
        ParamBinding(param_name="verified", literal=True),
        ParamBinding(param_name="source_label", literal=""),
        ParamBinding(param_name="gate_action", row_field="notes"),
    ],
    status_overrides=[
        StatusOverride(method="configure", state="configuring", status_text="hooks installed via CLI; no config write needed"),
        StatusOverride(method="prune", state="absent", status_text="hooks managed by CLI; no config to prune"),
        StatusOverride(method="dry_run", state="absent", status_text="would run install steps (dry-run)"),
    ],
)


def test_hooks_probe_and_dry_run_golden():
    r = assemble_hindsight_recipe(
        _row(recipe_kind=ProviderRecipeKind.HOOKS, status_command=""),
        _backend(),
        _HOOKS_SPEC,
    )
    assert _snap(r.probe({})) == {
        "success": True,
        "state": "absent",
        "status": "no status probe available",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manage_config_writes",
    }
    # dry_run uses spec override: "would run install steps (dry-run)"
    assert _snap(r.dry_run({})) == {
        "success": True,
        "state": "absent",
        "status": "would run install steps (dry-run)",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manage_config_writes",
    }


def test_hooks_unverified_fallback_golden():
    """Unverified hooks fall back to guidance-only via strategy.

    The _GUIDANCE_SPEC binds action_needed from row.notes; when notes is empty,
    the stamp falls through to row.audia_action (source gate rationale).
    """
    r = assemble_hindsight_recipe(
        _row(recipe_kind=ProviderRecipeKind.HOOKS, source_status="unconfirmed", notes="do X"),
        _backend(),
        _GUIDANCE_ONLY_SPEC,
    )
    assert _snap(r.probe({})) == {
        "success": True,
        "state": "absent",
        "status": "no automated integration available",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "do X",
    }


def test_plugin_config_probe_dry_run_golden():
    row = _row(recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG)
    r = PluginConfigRecipe(HindsightPluginDefinition.from_row(row), HindsightPluginDesired.from_backend(_backend()))
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
    row = _row(recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG)
    r = _PluginUrlConfigRecipe(
        HindsightPluginDefinition.from_row(row),
        HindsightPluginDesired.from_backend(_backend()),
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


def test_plugin_url_config_uninstall_removes_file(tmp_path):
    path = tmp_path / "url.json"
    row = _row(recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG)
    r = _PluginUrlConfigRecipe(
        HindsightPluginDefinition.from_row(row),
        HindsightPluginDesired.from_backend(_backend()),
        path,
    )
    r.configure({})

    result = r.uninstall({})

    assert result.success
    assert not path.exists()


def test_plugin_url_repair_resolves_appdata_placeholder(tmp_path, monkeypatch):
    cache = tmp_path / "cache" / "0.7.3"
    cache.mkdir(parents=True)
    mcp_path = cache / ".mcp.json"
    script = cache / "scripts" / "mcp_server.py"
    script.parent.mkdir()
    script.write_text("print('ok')\n", encoding="utf-8")
    appdata = tmp_path / "AppData" / "Roaming"
    venv_python = appdata / "Claude" / "plugins" / "data" / "hindsight-memory" / "venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    mcp_path.write_text(
        '{"mcpServers":{"hindsight":{"command":"bash","args":["run_mcp.sh"]}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("APPDATA", str(appdata))
    row = _row(
        recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
        plugin_repair_cache_pattern=str(tmp_path / "cache" / "*" / ".mcp.json"),
        plugin_repair_data_dir="${APPDATA}/Claude/plugins/data/hindsight-memory",
        plugin_repair_venv_python="venv/Scripts/python.exe",
        plugin_repair_server_script="scripts/mcp_server.py",
    )

    from audiagentic.components.memory.hindsight.plugin_definition import HindsightPluginDefinition

    ok, detail = _repair_windows_plugin_mcp(
        HindsightPluginDesired.from_backend(_backend()), HindsightPluginDefinition.from_row(row)
    )

    assert ok, detail
    import json

    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["hindsight"]["command"] == str(venv_python)


def test_plugin_array_probe_golden(tmp_path):
    package = "@vectorize-io/opencode-hindsight"
    row = _row(recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG, plugin_array_package=package)
    r = _PluginArrayRecipe(
        HindsightPluginDefinition.from_row(row),
        HindsightPluginDesired.from_backend(_backend()),
        tmp_path,
    )
    assert _snap(r.probe({})) == {
        "success": True,
        "state": "absent",
        "status": "plugin entry absent or stale",
        "source_url": "https://src.example/doc",
        "source_date": "2026-01-01",
        "action_needed": "manage_config_writes",
    }


def test_plugin_array_uninstall_removes_entry(tmp_path, monkeypatch):
    package = "@vectorize-io/opencode-hindsight"
    row = _row(
        recipe_kind=ProviderRecipeKind.PLUGIN_CONFIG,
        plugin_array_package=package,
    )
    r = _PluginArrayRecipe(HindsightPluginDefinition.from_row(row), HindsightPluginDesired.from_backend(_backend()), tmp_path)
    calls = []
    from audiagentic.components.providers.contracts.plugin_entry import PluginEntryResult
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.manage_plugin_entry",
        lambda *args, **kwargs: calls.append(kwargs["mode"]) or PluginEntryResult(True, True),
    )

    result = r.uninstall({})

    assert result.success
    assert calls == ["prune"]


def test_guidance_only_probe_provision_golden():
    r = assemble_hindsight_recipe(
        _row(source_status="unconfirmed", notes="manual note"),
        None,
        _GUIDANCE_ONLY_SPEC,
    )
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


def test_managed_mcp_payload_golden():
    from audiagentic.components.memory.hindsight.mcp_recipe import build_hindsight_managed_entry

    assert build_hindsight_managed_entry(_backend()).managed_id == "ag-hindsight"


def test_hybrid_kind_remains_matrix_classification_only():
    assert _row(recipe_kind=ProviderRecipeKind.HYBRID).recipe_kind is ProviderRecipeKind.HYBRID
