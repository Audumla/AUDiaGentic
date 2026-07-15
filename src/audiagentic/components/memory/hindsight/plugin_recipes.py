"""Hindsight plugin-integration recipes.

Recipes for providers whose Hindsight integration is a plugin: a plugin
registered in the harness config (:class:`PluginConfigRecipe`), a per-provider
settings JSON file with the Windows launcher repair
(:class:`_PluginUrlConfigRecipe`), or a declarative plugin-array entry
(:class:`_PluginArrayRecipe`).

All three consume only typed HindsightPluginDefinition and
HindsightPluginDesired objects. The raw HindsightRecipeRow exists only in the
matrix-to-definition parser.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.declared_integration import IntegrationCommand
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.mcp_recipe import (
    build_hindsight_managed_entry,
    hindsight_ownership_scope,
)
from audiagentic.components.memory.hindsight.plugin_definition import (
    HindsightPluginDefinition,
    HindsightPluginDesired,
)
from audiagentic.components.providers.services.recipes import (
    ProviderCapabilityRecipe,
    ProviderRecipeKind,
    ProviderRecipeResult,
    RecipeResult,
    RecipeState,
)
from audiagentic.foundation.steps import ShellStep
from audiagentic.foundation.toolchains.recipe_contract import run_steps


def _should_run_plugin_command(definition: HindsightPluginDefinition) -> bool:
    return definition.audia_action == "call_official_installer"


def _render_command(
    command: tuple[str, ...],
    desired: HindsightPluginDesired,
) -> tuple[str, ...]:
    """Render {URL}/{KEY}/{TOKEN}/{ID} placeholders in command parts."""
    values = {
        "URL": desired.endpoint_url,
        "KEY": desired.api_token or "",
        "TOKEN": desired.api_token or "",
        "ID": desired.bank_id or "",
    }
    return tuple(
        next((part.replace(f"{{{k}}}", v) for k, v in values.items() if f"{{{k}}}" in part), part)
        for part in command
    )


def _commands_to_steps(
    commands: tuple[IntegrationCommand, ...],
    desired: HindsightPluginDesired,
) -> list[ShellStep]:
    """Convert typed IntegrationCommand to ShellStep with rendered params."""
    return [
        ShellStep(
            id=cmd.id,
            command=_render_command(cmd.command, desired),
            shell=cmd.shell,
        )
        for cmd in commands
    ]


def _run_gated_steps(
    definition: HindsightPluginDefinition,
    desired: HindsightPluginDesired,
    commands: tuple[IntegrationCommand, ...],
    context: dict[str, Any],
    stamp_fn,
    *,
    operation: str,  # "install" or "uninstall"
) -> ProviderRecipeResult | None:
    """Run source-gated plugin install/uninstall steps.

    Returns the stamped result if steps were executed (success or failure),
    or None if no steps to run (caller handles fallback).
    """
    if not commands or not _should_run_plugin_command(definition):
        return None

    if definition.source_status != "verified":
        if operation == "uninstall":
            return stamp_fn(ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status=f"source {definition.source_status}; no plugin installer was executed",
                action_needed=definition.notes or definition.audia_action,
            ))
        return stamp_fn(ProviderRecipeResult.fail(
            f"plugin {operation} source {definition.source_status}; refusing to execute",
            action_needed=definition.notes or definition.audia_action,
        ))

    steps = _commands_to_steps(commands, desired)
    seq = run_steps(steps, context, fail_prefix=f"plugin {operation} failed")
    if not seq.success:
        return stamp_fn(seq)
    return None


class _PluginRecipe(ProviderCapabilityRecipe):
    """Base for Hindsight plugin recipes — consumes typed definition, not raw row."""

    capability_id = "hindsight"
    backend_id: str | None = None
    provision_via_steps = False

    def __init__(
        self,
        definition: HindsightPluginDefinition,
        *,
        recipe_kind: ProviderRecipeKind = ProviderRecipeKind.PLUGIN_CONFIG,
    ) -> None:
        super().__init__(
            provider_id=definition.provider_id,
            capability_id="hindsight",
            recipe_kind=recipe_kind,
            display_name=definition.display_name,
            source_url=definition.source_url,
            source_date=definition.source_date,
        )
        self._definition = definition

    def _stamp(
        self,
        result: RecipeResult | ProviderRecipeResult,
    ) -> ProviderRecipeResult:
        if isinstance(result, ProviderRecipeResult):
            return ProviderRecipeResult(
                success=result.success,
                state=result.state,
                artifacts_owned=list(result.artifacts_owned),
                status=result.status,
                error=result.error,
                details=dict(result.details or {}),
                source_url=result.source_url or self.source_url,
                source_date=result.source_date or self.source_date,
                action_needed=result.action_needed or self._definition.audia_action,
            )
        return ProviderRecipeResult(
            success=result.success,
            state=result.state,
            artifacts_owned=list(result.artifacts_owned),
            status=result.status,
            error=result.error,
            details=dict(result.details or {}),
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=result.action_needed or self._definition.audia_action,
        )

    def to_result(self, base: RecipeResult) -> ProviderRecipeResult:  # type: ignore[override]
        return self._stamp(base)


class PluginConfigRecipe(_PluginRecipe):
    """Plugin-config recipe: writes plugin registration to provider config.

    For providers like OpenCode, Claude that use plugin arrays or marketplace.
    When ``config_path`` is provided, uses the managed MCP ownership sync
    (provider machinery); otherwise falls back to CLI-managed no-ops.
    """

    def __init__(
        self,
        definition: HindsightPluginDefinition,
        desired: HindsightPluginDesired,
        config_path: Path | None = None,
    ) -> None:
        super().__init__(definition)
        self._desired = desired
        self._server_name = desired.endpoint_url.split("/")[2] if "//" in desired.endpoint_url else desired.endpoint_url
        self._managed_entry = build_hindsight_managed_entry(
            HindsightBackendConfig(
                base_url=desired.endpoint_url,
                api_key=desired.api_token,
                bank_id=desired.bank_id,
                server_name=self._server_name,
            )
        )
        self._ownership_scope = hindsight_ownership_scope(
            HindsightBackendConfig(
                base_url=desired.endpoint_url,
                api_key=desired.api_token,
                bank_id=desired.bank_id,
                server_name=self._server_name,
            )
        )
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
            self._definition, self._desired, self._definition.install_steps, context,
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
            self._definition, self._desired, self._definition.uninstall_steps, context,
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

    def provision_steps(self) -> list[ShellStep]:
        steps: list[ShellStep] = []
        if self._definition.install_steps and _should_run_plugin_command(self._definition):
            steps.extend(_commands_to_steps(self._definition.install_steps, self._desired))
        if self._definition.configure_steps:
            steps.extend(_commands_to_steps(self._definition.configure_steps, self._desired))
        return steps

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="would install plugin (dry-run)",
        ))


# RS18/RS06: intentional one-off — patches a third-party plugin file this recipe
# does not create or own; no shared primitive (WriteFileStep/ArtifactRegistry) applies.
def _repair_windows_plugin_mcp(
    desired: HindsightPluginDesired,
    definition: HindsightPluginDefinition,
) -> tuple[bool, str]:
    """On Windows, patch the installed hindsight plugin's .mcp.json to use python.exe.

    Uses typed repair metadata from HindsightPluginDefinition. Empty fields
    short-circuit as no-ops. The official plugin ships a bash launcher
    (run_mcp.sh) that fails when Git Bash is absent. Idempotent.
    """
    import glob
    import json
    import os

    cache_pattern_str = definition.repair_cache_pattern
    if not cache_pattern_str:
        return False, "no plugin repair metadata configured"

    expanded_pattern = Path(cache_pattern_str).expanduser()
    data_dir_str = definition.repair_data_dir
    venv_python_rel = definition.repair_venv_python
    server_script_rel = definition.repair_server_script

    mcp_files = glob.glob(str(expanded_pattern))
    if not mcp_files:
        return False, f"no .mcp.json found matching {expanded_pattern}"

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
            continue
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


def _build_plugin_url_config(desired: HindsightPluginDesired) -> dict[str, Any]:
    """Build the plugin URL config dict from desired, omitting unset optional fields."""
    return desired.options()


class _PluginUrlConfigRecipe(_PluginRecipe):
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
        definition: HindsightPluginDefinition,
        desired: HindsightPluginDesired,
        url_config_path: str | Path,
        harness_config_path: str | Path | None = None,
    ) -> None:
        super().__init__(definition)
        self._desired = desired
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

    def provision_steps(self) -> list[ShellStep]:
        steps: list[ShellStep] = []
        if self._definition.install_steps and _should_run_plugin_command(self._definition):
            steps.extend(_commands_to_steps(self._definition.install_steps, self._desired))
        if self._definition.configure_steps:
            steps.extend(_commands_to_steps(self._definition.configure_steps, self._desired))
        return steps

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        import os
        current = self._current_config()
        expected = self._expected_config()
        if all(current.get(k) == v for k, v in expected.items()):
            artifacts = [str(self._url_config_path)]
            if os.name == "nt":
                ok, detail = _repair_windows_plugin_mcp(self._desired, self._definition)
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
            self._definition, self._desired, self._definition.install_steps, context,
            self._stamp, operation="install",
        )
        if result is not None:
            return result
        return self._stamp(ProviderRecipeResult.ok(RecipeState.INSTALLING, status="plugin installed"))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        import os
        if self._definition.configure_steps:
            steps = _commands_to_steps(self._definition.configure_steps, self._desired)
            seq = run_steps(steps, context, fail_prefix="plugin configure failed")
            if not seq.success:
                return self._stamp(seq)
        from audiagentic.foundation.steps import WriteFileStep

        content = _build_plugin_url_config(self._desired)
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
            ok, detail = _repair_windows_plugin_mcp(self._desired, self._definition)
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
            self._definition, self._desired, self._definition.uninstall_steps, context,
            self._stamp, operation="uninstall",
        )
        if result is not None:
            return result
        return self.prune(context)

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self._url_config_path.unlink(missing_ok=True)
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin URL config removed",
        ))

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status=f"would write {self._url_config_path} (dry-run)",
        ))


class _PluginArrayRecipe(_PluginRecipe):
    """Upserts one named entry into a provider's declarative plugin-array config.

    For providers (e.g. OpenCode) that auto-install packages listed in a config
    array on startup rather than exposing an install command. All provider
    knowledge — config path, package name, and the reader/writer/remover that
    know the array's on-disk shape — comes from the typed definition; this class
    contains none.
    """

    def __init__(
        self,
        definition: HindsightPluginDefinition,
        desired: HindsightPluginDesired,
        project_root: Path,
    ) -> None:
        super().__init__(definition)
        self._desired = desired
        self._project_root = Path(project_root)
        if not definition.plugin_array_package:
            raise ValueError("plugin_array_package is required for _PluginArrayRecipe")
        self._package: str = definition.plugin_array_package

    def _expected_options(self) -> dict[str, Any]:
        return _build_plugin_url_config(self._desired)

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
