"""Hindsight plugin-integration recipes.

Recipes for providers whose Hindsight integration is a plugin: a plugin
registered in the harness config (:class:`PluginConfigRecipe`), a per-provider
settings JSON file with the Windows launcher repair
(:class:`_PluginUrlConfigRecipe`), or a declarative plugin-array entry
(:class:`_PluginArrayRecipe`).

Split from recipes.py; shares the ``_RowRecipe`` provenance base and the
``_hindsight_params`` vocabulary from that module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
from audiagentic.components.memory.hindsight.mcp_recipe import (
    build_hindsight_managed_entry,
    hindsight_ownership_scope,
)
from audiagentic.components.memory.hindsight.plugin_definition import (
    HindsightPluginDefinition,
    HindsightPluginDesired,
)
from audiagentic.components.memory.hindsight.recipes import _hindsight_params, _RowRecipe
from audiagentic.components.providers.services.recipes import (
    ProviderRecipeResult,
    RecipeState,
)
from audiagentic.foundation.steps import build_step
from audiagentic.foundation.toolchains.recipe_contract import run_steps


def _should_run_plugin_command(row: HindsightRecipeRow) -> bool:
    return row.audia_action == "call_official_installer"


def _build_steps(step_defs: list[Any], params: dict[str, str]) -> list[Any]:
    """Build step instances from YAML definitions using the canonical factory."""
    steps: list[Any] = []
    for defn in step_defs:
        step_data = dict(defn)
        step_data.setdefault("id", f"step-{len(steps)}")
        steps.append(build_step(step_data))
    return steps


def _run_gated_steps(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    step_defs: list[Any] | None,
    context: dict[str, Any],
    stamp_fn,
    *,
    operation: str,  # "install" or "uninstall"
) -> ProviderRecipeResult | None:
    """Run source-gated plugin install/uninstall steps.

    Returns the stamped result if steps were executed (success or failure),
    or None if no steps to run (caller handles fallback).
    """
    if not step_defs or not _should_run_plugin_command(row):
        return None

    if row.source_status != "verified":
        if operation == "uninstall":
            return stamp_fn(ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status=f"source {row.source_status}; no plugin installer was executed",
                action_needed=row.notes or row.audia_action,
            ))
        return stamp_fn(ProviderRecipeResult.fail(
            f"plugin {operation} source {row.source_status}; refusing to execute",
            action_needed=row.notes or row.audia_action,
        ))

    params = _hindsight_params(backend)
    steps = _build_steps(step_defs, params)
    seq = run_steps(steps, context, fail_prefix=f"plugin {operation} failed")
    if not seq.success:
        return stamp_fn(seq)
    return None


class PluginConfigRecipe(_RowRecipe):
    """Plugin-config recipe: writes plugin registration to provider config.

    For providers like OpenCode, Claude that use plugin arrays or marketplace.
    When ``config_path`` is provided, uses the managed MCP ownership sync
    (provider machinery); otherwise falls back to CLI-managed no-ops.
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        backend: HindsightBackendConfig,
        config_path: Path | None = None,
    ) -> None:
        super().__init__(row)
        self._backend = backend
        self._server_name = backend.server_name
        self._managed_entry = build_hindsight_managed_entry(backend)
        self._ownership_scope = hindsight_ownership_scope(backend)
        self._config_path = config_path

    def _mcp_status(self) -> dict[str, Any]:
        from audiagentic.components.providers.providers_api import (
            ManagedMcpRequest,
            manage_mcp_entries,
        )
        result = manage_mcp_entries(
            Path.cwd(), self.provider_id, mode="status",
            request=ManagedMcpRequest(
                ownership_scope=self._ownership_scope,
                entries=(self._managed_entry,),
            ),
        )
        return {"ok": result.supported, "present": result.ok, "matches": result.ok, "reason": result.error_code}

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._config_path:
            status = self._mcp_status()
            if not status["ok"]:
                return self._stamp(ProviderRecipeResult.ok(
                    RecipeState.ABSENT, status="entry absent",
                ))
            state = (
                RecipeState.VERIFIED if status["matches"] else RecipeState.ABSENT
            )
            return self._stamp(ProviderRecipeResult.ok(
                state,
                artifacts=[f"{self._config_path}::{self._server_name}"]
                if status["present"] else [],
                status="entry present" if status["present"] else "entry absent",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin config managed by CLI",
        ))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = _run_gated_steps(
            self._row, self._backend, self._row.install_steps, context,
            self._stamp, operation="install",
        )
        if result is not None:
            return result
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.INSTALLING, status="plugin installed",
        ))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._config_path:
            from audiagentic.components.providers.providers_api import (
                ManagedMcpRequest,
                manage_mcp_entries,
            )
            sync = manage_mcp_entries(
                Path.cwd(), self.provider_id, mode="apply",
                request=ManagedMcpRequest(
                    ownership_scope=self._ownership_scope,
                    entries=(self._managed_entry,),
                ),
            )
            if not sync.ok:
                return self._stamp(ProviderRecipeResult.fail(
                    f"managed MCP sync refused: {sync.collision_ids}",
                ))
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.CONFIGURING,
                artifacts=[self._server_name],
                status="entry written (managed)",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.CONFIGURING, status="plugin config applied",
        ))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._config_path:
            status = self._mcp_status()
            if not status["ok"]:
                return self._stamp(ProviderRecipeResult.fail("no mcp_config for this provider"))
            if status["matches"]:
                return self._stamp(ProviderRecipeResult.ok(
                    RecipeState.VERIFIED,
                    artifacts=[f"{self._config_path}::{self._server_name}"],
                ))
            return self._stamp(ProviderRecipeResult.fail(
                f"verify failed: entry {status['reason']}",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.VERIFIED, status="plugin verified",
        ))

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = _run_gated_steps(
            self._row, self._backend, self._row.uninstall_steps, context,
            self._stamp, operation="uninstall",
        )
        if result is not None:
            return result
        if self._config_path:
            return self.prune(context)
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin uninstalled",
        ))

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._config_path:
            # Fixture/custom paths without a registered provider cannot be
            # reconciled through provider-owned config machinery.  Never fall
            # back to a raw write; report the safe no-op instead.
            from audiagentic.components.providers.descriptors.registry import get_descriptor
            if get_descriptor(self.provider_id) is None:
                return self._stamp(ProviderRecipeResult.ok(
                    RecipeState.ABSENT,
                    status="no registered provider config to prune",
                ))
            from audiagentic.components.providers.providers_api import (
                ManagedMcpRequest,
                manage_mcp_entries,
            )
            manage_mcp_entries(
                Path.cwd(), self.provider_id, mode="prune",
                request=ManagedMcpRequest(ownership_scope=self._ownership_scope),
            )
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="entry removed (managed)",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="nothing to prune",
        ))

    def provision_steps(self) -> list[Any]:
        params = _hindsight_params(self._backend)
        if self._config_path:
            params["CONFIG_PATH"] = str(self._config_path)
        steps: list[Any] = []
        if self._row.install_steps and _should_run_plugin_command(self._row):
            steps.extend(_build_steps(
                self._row.install_steps, params,
            ))
        if self._row.configure_steps:
            steps.extend(_build_steps(
                self._row.configure_steps, params,
            ))
        return steps

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="would install plugin (dry-run)",
        ))


# RS18/RS06: intentional one-off — patches a third-party plugin file this recipe
# does not create or own; no shared primitive (WriteFileStep/ArtifactRegistry) applies.
def _repair_windows_plugin_mcp(
    backend: HindsightBackendConfig,
    definition: HindsightPluginDefinition | None = None,
) -> tuple[bool, str]:
    """On Windows, patch the installed hindsight plugin's .mcp.json to use python.exe.

    Uses YAML-driven repair metadata from the matrix row when available. Empty
    fields short-circuit as no-ops: if no cache pattern is configured, the
    function returns without attempting repair. The official plugin ships a
    bash launcher (run_mcp.sh) that fails when Git Bash is absent. Idempotent.
    """
    # Intentional one-off: patches third-party plugin .mcp.json file via glob discovery; no shared primitive covers OS-specific repair of unowned files (RS06/RS18)
    import glob
    import json
    import os

    # Empty metadata = no-op
    cache_pattern_str = definition.repair_cache_pattern if definition else ""
    if not cache_pattern_str:
        return False, "no plugin repair metadata configured"

    expanded_pattern = Path(cache_pattern_str).expanduser()
    data_dir_str = definition.repair_data_dir if definition else ""
    venv_python_rel = definition.repair_venv_python if definition else ""
    server_script_rel = definition.repair_server_script if definition else ""

    mcp_files = glob.glob(str(expanded_pattern))
    if not mcp_files:
        return False, f"no .mcp.json found matching {expanded_pattern}"

    # Resolve data directory from environment variable or fallback
    if data_dir_str:
        appdata = os.environ.get("APPDATA", "")
        if "${APPDATA}" in data_dir_str and not appdata:
            return False, "APPDATA not set; cannot resolve plugin data dir"
        data_dir = Path(data_dir_str.replace("${APPDATA}", appdata)).expanduser()
    else:
        return False, "plugin_repair_data_dir not configured"

    venv_python = data_dir / venv_python_rel if venv_python_rel else None
    if venv_python and not venv_python.exists():
        return False, (
            f"plugin venv not found at {venv_python}; "
            "run plugin installer first"
        )

    repaired: list[str] = []
    for mcp_path_str in mcp_files:
        mcp_path = Path(mcp_path_str)
        try:
            content = json.loads(mcp_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        servers = content.get("mcpServers", {})
        server = servers.get("hindsight", {})
        cmd = str(server.get("command", ""))
        if "python" in cmd.lower() and "bash" not in cmd.lower():
            continue  # already patched
        plugin_dir = mcp_path.parent
        mcp_script = (
            plugin_dir / server_script_rel if server_script_rel else plugin_dir / "scripts/mcp_server.py"
        )
        if not mcp_script.exists():
            continue
        servers["hindsight"] = {
            "command": str(venv_python) if venv_python else "",
            "args": [str(mcp_script)],
            "env": {
                "CLAUDE_PLUGIN_ROOT": str(plugin_dir),
                "CLAUDE_PLUGIN_DATA": str(data_dir),
            },
        }
        content["mcpServers"] = servers
        mcp_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        repaired.append(str(mcp_path))

    if repaired:
        return True, f"patched {'; '.join(repaired)}"
    return True, "already patched"


def _build_plugin_url_config(backend: HindsightBackendConfig) -> dict[str, Any]:
    """Build the plugin URL config dict from backend, omitting unset optional fields.

    This dict is written to provider-specific config files (e.g.
    ~/.hindsight/claude-code.json, ~/.hindsight/opencode.json) so the provider's
    Hindsight plugin reads the correct server URL, token, and bank. Fields are
    only included when the backend has a value — the plugin's own defaults apply
    for absent keys, and empty strings are not written.
    """
    return HindsightPluginDesired.from_backend(backend).options()


class _PluginUrlConfigRecipe(_RowRecipe):
    """Writes hindsight connection config to a provider-specific JSON file.

    Used by providers whose Hindsight plugin reads a ~/.hindsight/<provider>.json
    file for URL, token, and bank settings (e.g. Claude's claude-code.json,
    OpenCode's opencode.json). The file is written in code so optional fields
    (token, bankId) are included only when set — YAML template substitution cannot
    handle optional JSON keys cleanly.

    On Windows, configure also patches the Claude plugin's auto-generated .mcp.json
    to use python.exe instead of bash (the plugin ships a bash launcher that fails
    when Git Bash is absent). This repair is a no-op for non-Claude providers.

    ``harness_config_path`` is set when the provider's configure_steps use
    {CONFIG_PATH} to refer to the harness config file (e.g. opencode.json for the
    plugin array). It is separate from ``url_config_path`` (the hindsight settings
    file). Falls back to url_config_path when not provided.
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        backend: HindsightBackendConfig,
        url_config_path: str | Path,
        harness_config_path: str | Path | None = None,
    ) -> None:
        super().__init__(row)
        self._backend = backend
        self._definition = HindsightPluginDefinition.from_row(row)
        self._desired = HindsightPluginDesired.from_backend(backend)
        self._url_config_path = Path(url_config_path).expanduser()
        self._harness_config_path = Path(harness_config_path) if harness_config_path else None

    def _expected_config(self) -> dict[str, Any]:
        return self._desired.options()

    def _current_config(self) -> dict[str, Any]:
        try:
            import json
            return json.loads(self._url_config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def provision_steps(self) -> list[Any]:
        params = _hindsight_params(self._backend)
        # configure_steps use {CONFIG_PATH} for the harness config (plugin array etc.),
        # not the url config file. Fall back to url_config_path when no harness path.
        config_path_for_steps = self._harness_config_path or self._url_config_path
        params["CONFIG_PATH"] = str(config_path_for_steps)
        steps: list[Any] = []
        if self._row.install_steps and _should_run_plugin_command(self._row):
            steps.extend(_build_steps(
                self._row.install_steps, params,
            ))
        if self._row.configure_steps:
            steps.extend(_build_steps(
                self._row.configure_steps, params,
            ))
        return steps

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        import os
        current = self._current_config()
        expected = self._expected_config()
        if all(current.get(k) == v for k, v in expected.items()):
            artifacts = [str(self._url_config_path)]
            if os.name == "nt":
                ok, detail = _repair_windows_plugin_mcp(self._backend, self._definition)
                if ok and "patched" in detail:
                    artifacts.append(detail)
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.VERIFIED,
                artifacts=artifacts,
                status="plugin URL config correct",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin URL config absent or stale",
        ))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = _run_gated_steps(
            self._row, self._backend, self._row.install_steps, context,
            self._stamp, operation="install",
        )
        if result is not None:
            return result
        return self._stamp(ProviderRecipeResult.ok(RecipeState.INSTALLING, status="plugin installed"))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        import os
        if self._row.configure_steps:
            params = _hindsight_params(self._backend)
            config_path_for_steps = self._harness_config_path or self._url_config_path
            params["CONFIG_PATH"] = str(config_path_for_steps)
            steps = _build_steps(
                self._row.configure_steps, params,
            )
            seq = run_steps(steps, context, fail_prefix="plugin configure failed")
            if not seq.success:
                return self._stamp(seq)
        # Direct write: JSON config content built by _build_plugin_url_config(); WriteFileStep not used because this recipe doesn't maintain an ArtifactRegistry instance (RS06/RS18)
        from audiagentic.foundation.steps import WriteFileStep

        content = _build_plugin_url_config(self._backend)
        import json
        step = WriteFileStep(
            id="plugin-url-config-write",
            path=str(self._url_config_path),
            content=json.dumps(content, indent=2),
            create_parents=True,
            recipe_id=f"hindsight-{self.provider_id}",
        )
        step.run(context)
        artifacts = [str(self._url_config_path)]
        if os.name == "nt":
            ok, detail = _repair_windows_plugin_mcp(self._backend, self._definition)
            if ok and "patched" in detail:
                artifacts.append(detail)
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.CONFIGURING, artifacts=artifacts, status="plugin URL config written",
        ))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        probed = self.probe(context)
        if probed.success and probed.state is RecipeState.VERIFIED:
            return probed
        return self._stamp(ProviderRecipeResult.fail("plugin URL config not verified after configure"))

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = _run_gated_steps(
            self._row, self._backend, self._row.uninstall_steps, context,
            self._stamp, operation="uninstall",
        )
        if result is not None:
            return result
        return self.prune(context)

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        # Direct prune: URL config file not registered with ArtifactRegistry; bare unlink is acceptable for self-owned files (RS06/RS18)
        self._url_config_path.unlink(missing_ok=True)
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin URL config removed",
        ))

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status=f"would write {self._url_config_path} (dry-run)",
        ))


class _PluginArrayRecipe(_RowRecipe):
    """Upserts one named entry into a provider's declarative plugin-array config.

    For providers (e.g. OpenCode) that auto-install packages listed in a config
    array on startup rather than exposing an install command. All provider
    knowledge — config path, package name, and the reader/writer/remover that
    know the array's on-disk shape — comes from the matrix row; this class
    contains none.
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        backend: HindsightBackendConfig,
        project_root: Path,
    ) -> None:
        super().__init__(row)
        self._backend = backend
        self._project_root = Path(project_root)
        self._package = row.plugin_array_package

    def _expected_options(self) -> dict[str, Any]:
        return _build_plugin_url_config(self._backend)

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        from audiagentic.components.providers.providers_api import (
            PluginEntryRequest,
            manage_plugin_entry,
        )

        result = manage_plugin_entry(
            self._project_root, self.provider_id, mode="status",
            request=PluginEntryRequest(self._package, tuple(self._expected_options().items())),
        )
        if result.ok and result.present:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.VERIFIED, status="plugin entry present",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin entry absent or stale",
        ))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.INSTALLING, status="plugin auto-installs from config array; no install step",
        ))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        from audiagentic.components.providers.providers_api import (
            PluginEntryRequest,
            manage_plugin_entry,
        )

        result = manage_plugin_entry(
            self._project_root, self.provider_id, mode="apply",
            request=PluginEntryRequest(self._package, tuple(self._expected_options().items())),
        )
        if not result.ok:
            return self._stamp(ProviderRecipeResult.fail(result.error_code or "plugin entry write failed"))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.CONFIGURING, status="plugin array entry written",
        ))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        probed = self.probe(context)
        if probed.success and probed.state is RecipeState.VERIFIED:
            return probed
        return self._stamp(ProviderRecipeResult.fail("plugin array entry not verified after configure"))

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.prune(context)

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        from audiagentic.components.providers.providers_api import (
            PluginEntryRequest,
            manage_plugin_entry,
        )

        manage_plugin_entry(
            self._project_root, self.provider_id, mode="prune",
            request=PluginEntryRequest(self._package),
        )
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin array entry removed",
        ))

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        probed = self.probe(context)
        if probed.state is RecipeState.VERIFIED:
            return probed
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status=f"would write {self._package} plugin entry (dry-run)",
        ))


__all__ = [
    "PluginConfigRecipe",
]
