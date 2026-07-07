"""Hindsight provider recipe implementations.

Recipe classes only: strategy selection lives in strategies.py, the
apply/teardown/prune orchestration in lifecycle.py, and aggregate status
in status.py. Hindsight-specific provider setup is contained here; the
providers component exposes only generic recipe interfaces.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.export import (
    HindsightBackendConfig,
)
from audiagentic.components.memory.hindsight.matrix import (
    HindsightRecipeRow,
)
from audiagentic.components.memory.hindsight.mcp_recipe import (
    HindsightMcpRecipe,
    HindsightTarget,
    build_hindsight_mcp_entry,
)
from audiagentic.components.providers.services.recipes import (
    ProviderCapabilityRecipe,
    ProviderRecipeKind,
    ProviderRecipeResult,
    RecipeResult,
    RecipeState,
)
from audiagentic.foundation.refs import resolve_ref
from audiagentic.foundation.toolchains.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.managed_block import (
    apply_managed_block,
    block_artifact_id,
    remove_managed_block,
)
from audiagentic.foundation.toolchains.probes import CommandProbe, safe_command_parts
from audiagentic.foundation.toolchains.provision_steps import (
    ManagedBlockStep,
    ProvisionStep,
    steps_from_defs,
    substitute_params,
)
from audiagentic.foundation.toolchains.recipe_contract import run_steps

logger = logging.getLogger(__name__)


#: Managed-mcp registry id under which the hindsight entry is owned. Ownership
#: rides the same managed sync as ag-* servers, so managed tooling can see,
#: collision-check, and prune the entry; ag-* projections use subset sync and
#: never touch this id.
HINDSIGHT_MANAGED_ID = "ag-hindsight"


def _sync_hindsight_mcp_entry(
    provider_id: str,
    project_root: Path | None,
    backend: HindsightBackendConfig | None,
    *,
    remove: bool = False,
) -> dict[str, Any]:
    """Write/remove the hindsight MCP entry through the managed ownership sync."""
    from audiagentic.components.providers.services.mcp import (
        sync_managed_provider_mcp_subset,
    )

    root = Path(project_root) if project_root else Path.cwd()
    desired: dict[str, Any] = {}
    if not remove and backend is not None:
        desired[HINDSIGHT_MANAGED_ID] = (
            backend.server_name,
            build_hindsight_mcp_entry(backend),
        )
    return sync_managed_provider_mcp_subset(
        provider_id, root, desired, managed_ids={HINDSIGHT_MANAGED_ID}
    )


RULE_TEXT = """Use Hindsight memory when prior project context may help.
- Recall before design/history questions or non-trivial work.
- Retain durable decisions, user preferences, architecture constraints, and outcomes.
- Do not retain secrets, credentials, or transient noise.
"""
_RULE_BLOCK_ID = "hindsight-memory"


def _absolute_project_path(path: str | Path, project_root: Path | None = None) -> Path:
    target = Path(path).expanduser()
    if target.is_absolute() or project_root is None:
        return target
    return Path(project_root) / target



class _RowRecipe(ProviderCapabilityRecipe):
    """Common provider metadata + result re-stamping for Hindsight recipes.

    Extends ProviderCapabilityRecipe with Hindsight-specific provenance and
    action-guidance overlay drawn from a matrix row. Provision/teardown
    orchestration comes from the ProvisioningRecipe base, with every result
    routed through :meth:`to_result` for the provenance overlay.
    """

    capability_id = "hindsight"
    backend_id: str | None = None
    # provision_steps() on these recipes exists for matrix-step introspection
    # and dry-run tooling; configure() often does work the steps cannot
    # express (inner MCP writes, URL-config files, registry registration), so
    # execution always uses the primitive path.
    provision_via_steps = False

    def __init__(
        self,
        row: HindsightRecipeRow,
        *,
        recipe_kind: ProviderRecipeKind | None = None,
    ) -> None:
        super().__init__(
            provider_id=row.provider_id,
            capability_id="hindsight",
            recipe_kind=recipe_kind if recipe_kind is not None else row.recipe_kind,
            display_name=row.display_name,
            source_url=row.source_url,
            source_date=row.source_date,
        )
        self._row = row

    def _stamp(self, result: Any) -> ProviderRecipeResult:
        """Re-stamp any recipe result with this provider's provenance."""
        return ProviderRecipeResult(
            success=result.success,
            state=result.state,
            artifacts_owned=list(result.artifacts_owned),
            status=result.status,
            error=getattr(result, "error", None),
            details=dict(getattr(result, "details", {}) or {}),
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=getattr(result, "action_needed", "") or self._row.audia_action,
        )

    def to_result(self, base: RecipeResult) -> ProviderRecipeResult:  # type: ignore[override]
        """Convert generic result with Hindsight provenance overlay."""
        return self._stamp(base)


class HooksInstallerRecipe(_RowRecipe):
    """Command-installer recipe: runs official hook installer CLI.

    For providers like Codex, Cline that use hook scripts installed via CLI.
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        backend: HindsightBackendConfig,
    ) -> None:
        super().__init__(row)
        self._backend = backend

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.source_status != "verified":
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status=f"source {self._row.source_status}; installer blocked",
                action_needed=self._row.notes or self._row.audia_action,
            ))
        if not self._row.status_command:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="no status probe available",
            ))
        try:
            cmd = _parameterize_command(self._row.status_command, self._backend)
            probe = CommandProbe(tuple(safe_command_parts(cmd)), expect_exit=0, timeout=15)
            result = probe.check()
            state = RecipeState.VERIFIED if result.passed else RecipeState.ABSENT
            return self._stamp(ProviderRecipeResult.ok(state, status=result.detail))
        except Exception as exc:
            logger.error(
                "probe failed for provider %s: %s",
                self.provider_id,
                exc,
                exc_info=True,
            )
            return self._stamp(ProviderRecipeResult.fail(str(exc)))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.source_status != "verified":
            return self._stamp(ProviderRecipeResult.fail(
                f"installer source {self._row.source_status}; refusing to execute",
                action_needed=self._row.notes or self._row.audia_action,
            ))
        if not self._row.install_steps:
            return self._stamp(ProviderRecipeResult.fail(
                "no install steps for this provider",
            ))
        params = _hindsight_params(self._backend)
        steps = steps_from_defs(self._row.install_steps, params)
        return self._stamp(run_steps(
            steps, context,
            ok_state=RecipeState.INSTALLING,
            ok_status="installer succeeded",
            fail_prefix="installer failed",
        ))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.CONFIGURING,
            status="hooks installed via CLI; no config write needed",
        ))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if not self._row.status_command:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.VERIFIED,
                status="installer completed; no status probe available",
            ))
        return self.probe(context)

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.source_status != "verified":
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status=f"source {self._row.source_status}; no installer was executed",
                action_needed=self._row.notes or self._row.audia_action,
            ))
        if not self._row.uninstall_steps:
            return self._stamp(ProviderRecipeResult.fail(
                "no uninstall steps for this provider",
            ))
        params = _hindsight_params(self._backend)
        steps = steps_from_defs(self._row.uninstall_steps, params)
        return self._stamp(run_steps(
            steps, context,
            ok_state=RecipeState.ABSENT,
            ok_status="uninstaller succeeded",
            fail_prefix="uninstaller failed",
        ))

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="hooks managed by CLI; no config to prune",
        ))

    def provision_steps(self) -> list[ProvisionStep]:
        params = _hindsight_params(self._backend)
        return steps_from_defs(
            self._row.install_steps, params,
            recipe_id=f"hindsight-{self.provider_id}",
        )

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.install_steps:
            step_info = ", ".join(s.get("id", str(i)) for i, s in enumerate(self._row.install_steps))
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status=f"would run install steps [{step_info}] (dry-run)",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="no install steps (dry-run)",
        ))


class PluginConfigRecipe(_RowRecipe):
    """Plugin-config recipe: writes plugin registration to provider config.

    For providers like OpenCode, Claude that use plugin arrays or marketplace.
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        backend: HindsightBackendConfig,
        target: HindsightTarget | None = None,
    ) -> None:
        super().__init__(row)
        self._backend = backend
        self._target = target
        self._inner = HindsightMcpRecipe(backend, target) if target else None

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._inner:
            return self._stamp(self._inner.probe(context))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin config managed by CLI",
        ))

    def _should_run_plugin_command(self) -> bool:
        return self._row.audia_action == "call_official_installer"

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.install_steps and self._should_run_plugin_command():
            if self._row.source_status != "verified":
                return self._stamp(ProviderRecipeResult.fail(
                    f"plugin installer source {self._row.source_status}; refusing to execute",
                    action_needed=self._row.notes or self._row.audia_action,
                ))
            params = _hindsight_params(self._backend)
            steps = steps_from_defs(self._row.install_steps, params)
            seq = run_steps(steps, context, fail_prefix="plugin install failed")
            if not seq.success:
                return self._stamp(seq)
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.INSTALLING, status="plugin installed",
        ))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._inner:
            return self._stamp(self._inner.configure(context))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.CONFIGURING, status="plugin config applied",
        ))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._inner:
            return self._stamp(self._inner.verify(context))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.VERIFIED, status="plugin verified",
        ))

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.uninstall_steps and self._should_run_plugin_command():
            if self._row.source_status != "verified":
                return self._stamp(ProviderRecipeResult.ok(
                    RecipeState.ABSENT,
                    status=f"source {self._row.source_status}; no plugin installer was executed",
                    action_needed=self._row.notes or self._row.audia_action,
                ))
            params = _hindsight_params(self._backend)
            steps = steps_from_defs(self._row.uninstall_steps, params)
            seq = run_steps(steps, context, fail_prefix="plugin uninstall failed")
            if not seq.success:
                return self._stamp(seq)
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin uninstalled",
        ))

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._inner:
            return self._stamp(self._inner.prune(context))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="nothing to prune",
        ))

    def provision_steps(self) -> list[ProvisionStep]:
        params = _hindsight_params(self._backend)
        if self._target and self._target.config_path:
            params["CONFIG_PATH"] = str(self._target.config_path)
        steps: list[ProvisionStep] = []
        if self._row.install_steps and self._should_run_plugin_command():
            steps.extend(steps_from_defs(
                self._row.install_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        if self._row.configure_steps:
            steps.extend(steps_from_defs(
                self._row.configure_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        return steps

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="would install plugin (dry-run)",
        ))


def _repair_windows_plugin_mcp(
    backend: HindsightBackendConfig,
    row: HindsightRecipeRow | None = None,
) -> tuple[bool, str]:
    """On Windows, patch the installed hindsight plugin's .mcp.json to use python.exe.

    Uses YAML-driven repair metadata from the matrix row when available. Empty
    fields short-circuit as no-ops: if no cache pattern is configured, the
    function returns without attempting repair. The official plugin ships a
    bash launcher (run_mcp.sh) that fails when Git Bash is absent. Idempotent.
    """
    import glob
    import json
    import os

    # Empty metadata = no-op
    cache_pattern_str = getattr(row, "plugin_repair_cache_pattern", "") if row else ""
    if not cache_pattern_str:
        return False, "no plugin repair metadata configured"

    expanded_pattern = Path(cache_pattern_str).expanduser()
    data_dir_str = getattr(row, "plugin_repair_data_dir", "") if row else ""
    venv_python_rel = getattr(row, "plugin_repair_venv_python", "") if row else ""
    server_script_rel = getattr(row, "plugin_repair_server_script", "") if row else ""

    mcp_files = glob.glob(str(expanded_pattern))
    if not mcp_files:
        return False, f"no .mcp.json found matching {expanded_pattern}"

    # Resolve data directory from environment variable or fallback
    if data_dir_str:
        raw_data = Path(data_dir_str)
        appdata = os.environ.get("APPDATA", "")
        if "${APPDATA}" in data_dir_str and not appdata:
            return False, "APPDATA not set; cannot resolve plugin data dir"
        data_dir = raw_data.expanduser()
        if "${APPDATA}" in data_dir_str:
            data_dir = Path(appdata) / str(raw_data).split("/Claude/")[1]
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
    config: dict[str, Any] = {"hindsightApiUrl": backend.base_url}
    if backend.api_key:
        config["hindsightApiToken"] = backend.api_key
    if backend.bank_id:
        config["bankId"] = backend.bank_id
    return config


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
        self._url_config_path = Path(url_config_path).expanduser()
        self._harness_config_path = Path(harness_config_path) if harness_config_path else None

    def _expected_config(self) -> dict[str, Any]:
        return _build_plugin_url_config(self._backend)

    def _current_config(self) -> dict[str, Any]:
        try:
            import json
            return json.loads(self._url_config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def provision_steps(self) -> list[ProvisionStep]:
        params = _hindsight_params(self._backend)
        # configure_steps use {CONFIG_PATH} for the harness config (plugin array etc.),
        # not the url config file. Fall back to url_config_path when no harness path.
        config_path_for_steps = self._harness_config_path or self._url_config_path
        params["CONFIG_PATH"] = str(config_path_for_steps)
        steps: list[ProvisionStep] = []
        if self._row.install_steps and self._should_run_plugin_command():
            steps.extend(steps_from_defs(
                self._row.install_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        if self._row.configure_steps:
            steps.extend(steps_from_defs(
                self._row.configure_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        return steps

    def _should_run_plugin_command(self) -> bool:
        return self._row.audia_action == "call_official_installer"

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        current = self._current_config()
        expected = self._expected_config()
        if all(current.get(k) == v for k, v in expected.items()):
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.VERIFIED,
                artifacts=[str(self._url_config_path)],
                status="plugin URL config correct",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin URL config absent or stale",
        ))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.install_steps and self._should_run_plugin_command():
            if self._row.source_status != "verified":
                return self._stamp(ProviderRecipeResult.fail(
                    f"plugin installer source {self._row.source_status}; refusing to execute",
                    action_needed=self._row.notes or self._row.audia_action,
                ))
            params = _hindsight_params(self._backend)
            steps = steps_from_defs(self._row.install_steps, params)
            seq = run_steps(steps, context, fail_prefix="plugin install failed")
            if not seq.success:
                return self._stamp(seq)
        return self._stamp(ProviderRecipeResult.ok(RecipeState.INSTALLING, status="plugin installed"))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        import json
        import os
        if self._row.configure_steps:
            params = _hindsight_params(self._backend)
            config_path_for_steps = self._harness_config_path or self._url_config_path
            params["CONFIG_PATH"] = str(config_path_for_steps)
            steps = steps_from_defs(
                self._row.configure_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            )
            seq = run_steps(steps, context, fail_prefix="plugin configure failed")
            if not seq.success:
                return self._stamp(seq)
        self._url_config_path.parent.mkdir(parents=True, exist_ok=True)
        self._url_config_path.write_text(
            json.dumps(self._expected_config(), indent=2),
            encoding="utf-8",
        )
        artifacts = [str(self._url_config_path)]
        if os.name == "nt":
            ok, detail = _repair_windows_plugin_mcp(self._backend, self._row)
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
        if self._row.uninstall_steps and self._should_run_plugin_command():
            if self._row.source_status != "verified":
                return self._stamp(ProviderRecipeResult.ok(
                    RecipeState.ABSENT,
                    status=f"source {self._row.source_status}; no plugin installer was executed",
                    action_needed=self._row.notes or self._row.audia_action,
                ))
            params = _hindsight_params(self._backend)
            steps = steps_from_defs(self._row.uninstall_steps, params)
            seq = run_steps(steps, context, fail_prefix="plugin uninstall failed")
            if not seq.success:
                return self._stamp(seq)
        return self._stamp(ProviderRecipeResult.ok(RecipeState.ABSENT, status="plugin uninstalled"))

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
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
        config_path: str | Path,
    ) -> None:
        super().__init__(row)
        self._backend = backend
        self._path = Path(config_path).expanduser()
        self._package = row.plugin_array_package
        self._reader = resolve_ref(row.plugin_array_reader) if row.plugin_array_reader else None
        self._writer = resolve_ref(row.plugin_array_writer) if row.plugin_array_writer else None
        self._remover = resolve_ref(row.plugin_array_remover) if row.plugin_array_remover else None

    def _expected_options(self) -> dict[str, Any]:
        return _build_plugin_url_config(self._backend)

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if not self._reader:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="no reader configured for plugin array",
            ))
        current = self._reader(self._path, self._package)
        if current is not None and current == self._expected_options():
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.VERIFIED, artifacts=[str(self._path)], status="plugin entry present",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin entry absent or stale",
        ))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.INSTALLING, status="plugin auto-installs from config array; no install step",
        ))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if not self._writer:
            return self._stamp(ProviderRecipeResult.fail("no writer configured for plugin array"))
        self._writer(self._path, self._package, self._expected_options())
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.CONFIGURING, artifacts=[str(self._path)], status="plugin array entry written",
        ))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        probed = self.probe(context)
        if probed.success and probed.state is RecipeState.VERIFIED:
            return probed
        return self._stamp(ProviderRecipeResult.fail("plugin array entry not verified after configure"))

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin managed via config array; nothing to uninstall",
        ))

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._remover:
            self._remover(self._path, self._package)
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin array entry removed",
        ))

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        probed = self.probe(context)
        if probed.state is RecipeState.VERIFIED:
            return probed
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status=f"would write {self._package} to {self._path} (dry-run)",
        ))


class GuidanceOnlyRecipe(_RowRecipe):
    """Guidance-only recipe: no automation, action-needed guidance only.

    For providers with no official Hindsight integration yet.
    """

    def __init__(self, row: HindsightRecipeRow) -> None:
        super().__init__(row, recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY)

    def provision(self, context: dict[str, Any]) -> ProviderRecipeResult:
        """Provisioning a guidance-only provider is a clean no-op, not a failure.

        There is no automated integration to run, so reconciliation reports a
        successful skip with optional manual-setup guidance rather than an error.
        """
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="skipped: no automated Hindsight integration for this provider",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.notes or "manual setup optional",
        )

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="no automated integration available",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.notes or "manual setup required",
        )

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.fail(
            "no automated install for this provider",
            source_url=self.source_url,
            action_needed=self._row.notes or "manual setup required",
        )

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.install(context)

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.probe(context)

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="nothing to uninstall",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="nothing to prune",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.probe(context)


class RulesOnlyRecipe(_RowRecipe):
    """Rule-block recipe for providers with instructions but no native installer."""

    def __init__(
        self,
        row: HindsightRecipeRow,
        rule_path: str | Path,
        *,
        project_root: Path | None = None,
    ) -> None:
        super().__init__(row, recipe_kind=ProviderRecipeKind.RULES)
        self._project_root = Path(project_root) if project_root else None
        self._rule_path = _absolute_project_path(rule_path, self._project_root)
        self.recipe_id = f"hindsight:{self.provider_id}:rules"

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if not self._rule_path.exists():
            return ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status="rule block absent",
                source_url=self.source_url,
                source_date=self.source_date,
                action_needed=self._row.audia_action,
            )
        text = self._rule_path.read_text(encoding="utf-8")
        state = (
            RecipeState.VERIFIED
            if f"audiagentic:{_RULE_BLOCK_ID}" in text
            else RecipeState.ABSENT
        )
        return ProviderRecipeResult.ok(
            state,
            artifacts=[block_artifact_id(self._rule_path, _RULE_BLOCK_ID)]
            if state is RecipeState.VERIFIED
            else [],
            status="rule block present" if state is RecipeState.VERIFIED else "rule block absent",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.INSTALLING,
            status="rules-only integration",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        change = apply_managed_block(self._rule_path, _RULE_BLOCK_ID, RULE_TEXT)
        if self._project_root:
            ArtifactRegistry(self._project_root).register(self.recipe_id, blocks=[change])
        return ProviderRecipeResult.ok(
            RecipeState.CONFIGURING,
            artifacts=[change.artifact_id],
            status="rule block written",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = self.probe(context)
        if result.state is RecipeState.VERIFIED:
            return result
        return ProviderRecipeResult.fail(
            "rule block missing after configure",
            source_url=self.source_url,
            action_needed=self._row.audia_action,
        )

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="rules-only integration",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._project_root:
            report = ArtifactRegistry(self._project_root).prune(self.recipe_id)
            if not report.ok:
                return ProviderRecipeResult.fail(
                    "; ".join(report.errors),
                    source_url=self.source_url,
                    action_needed=self._row.audia_action,
                )
            return ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status=f"removed {len(report.removed_blocks)} rule blocks",
                source_url=self.source_url,
                source_date=self.source_date,
            )
        change = remove_managed_block(self._rule_path, _RULE_BLOCK_ID)
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="rule block removed" if change.existed else "rule block already absent",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def provision_steps(self) -> list[ProvisionStep]:
        if self._row.configure_steps:
            params = {"URL": "", "MCP_URL": "", "TOKEN": "", "KEY": "", "ID": ""}
            return steps_from_defs(
                self._row.configure_steps, params,
                recipe_id=self.recipe_id,
            )
        return [
            ManagedBlockStep(
                id="write-rule-block",
                path=str(self._rule_path),
                block_id=_RULE_BLOCK_ID,
                content=RULE_TEXT,
                recipe_id=self.recipe_id,
            )
        ]

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        probed = self.probe(context)
        if probed.state is RecipeState.VERIFIED:
            return ProviderRecipeResult.ok(
                RecipeState.VERIFIED,
                status="already provisioned (dry-run)",
                source_url=self.source_url,
                source_date=self.source_date,
                action_needed=self._row.audia_action,
            )
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status=f"would write rule block to {self._rule_path}",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def to_result(self, base) -> ProviderRecipeResult:
        return base


def _parameterize_command(
    command: str,
    backend: HindsightBackendConfig,
) -> str:
    """Replace {URL}/{MCP_URL}/{TOKEN}/{KEY}/{ID} placeholders with backend values."""
    return substitute_params(command, _hindsight_params(backend))


def _hindsight_params(backend: HindsightBackendConfig) -> dict[str, str]:
    """Build params dict from backend config for ProvisionStep placeholder substitution.

    Supported keys: URL, MCP_URL, TOKEN, KEY, ID.
    All keys are always present; optional fields (TOKEN, KEY, ID) default to ""
    so YAML steps can reference them without raising on unknown placeholders.
    ShellProvisionStep filters out --flag= args with empty values at run time.
    """
    return {
        "URL": backend.base_url,
        "MCP_URL": backend.mcp_url or "",
        "TOKEN": backend.api_key or "",
        "KEY": backend.api_key or "",
        "ID": backend.bank_id or "",
    }



class _McpConfigAdapter(_RowRecipe):
    """Thin adapter that wraps HindsightMcpRecipe with provider metadata.

    Probe/verify delegate to the inner recipe (descriptor-reader comparison);
    configure/prune go through the managed ownership sync so the hindsight
    entry is registered in managed-mcp-servers.json like every other
    AUDiaGentic-owned entry (HM21/RV155). Results are re-stamped with this
    provider's provenance via ``_stamp``.
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        inner: HindsightMcpRecipe,
        project_root: Path | None = None,
    ) -> None:
        super().__init__(row)
        self._inner = inner
        self._project_root = project_root

    def provision_steps(self) -> list[ProvisionStep]:
        params = _hindsight_params(self._inner.backend)
        steps: list[ProvisionStep] = []
        # Row-level install/uninstall steps from matrix (e.g. pip install + init)
        if self._row.install_steps:
            steps.extend(steps_from_defs(
                self._row.install_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        # Row-level configure steps (e.g. config-set for plugin arrays)
        if self._row.configure_steps:
            steps.extend(steps_from_defs(
                self._row.configure_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        # Inner MCP config steps (only for JSON-based configs without callbacks)
        inner_fn = getattr(self._inner, "provision_steps", None)
        if callable(inner_fn):
            steps.extend(inner_fn())  # type: ignore[misc]
        return steps

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(self._inner.probe(context))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(self._inner.install(context))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        sync = _sync_hindsight_mcp_entry(
            self.provider_id, self._project_root, self._inner.backend
        )
        if not sync.get("ok"):
            return self._stamp(ProviderRecipeResult.fail(
                f"managed MCP sync refused: {sync.get('collisions')}",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.CONFIGURING,
            artifacts=[f"{sync.get('config_path')}::{self._inner.backend.server_name}"],
            status="entry written (managed)",
        ))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(self._inner.verify(context))

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(self._inner.uninstall(context))

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        # Single removal path regardless of when the entry was written: the
        # server name is ours by construction, so remove it by name via the
        # inner recipe, then clear the ownership record (idempotent).
        result = self._inner.prune(context)
        _sync_hindsight_mcp_entry(
            self.provider_id, self._project_root, self._inner.backend, remove=True
        )
        return self._stamp(result)

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = self._inner.probe(context)
        verified = result.success and result.state is RecipeState.VERIFIED
        state = RecipeState.VERIFIED if verified else RecipeState.ABSENT
        return self._stamp(ProviderRecipeResult.ok(
            state,
            status="already provisioned (dry-run)" if verified else "would install (dry-run)",
        ))

    def to_result(self, base) -> ProviderRecipeResult:
        return self._stamp(base)


class _CompositeRecipe(_RowRecipe):
    """Wraps an MCP config recipe and a rules recipe, executing both in sequence.

    The MCP entry write/remove goes through the managed ownership sync
    (HM21/RV155); the inner recipe remains the probe/verify reader.
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        mcp_inner: HindsightMcpRecipe,
        rules_inner: RulesOnlyRecipe,
        project_root: Path | None = None,
    ) -> None:
        super().__init__(row)
        self._mcp = mcp_inner
        self._rules = rules_inner
        self._project_root = project_root

    def provision_steps(self) -> list[ProvisionStep]:
        backend = self._mcp.backend
        params = _hindsight_params(backend)
        steps: list[ProvisionStep] = []
        # Row-level install steps first (e.g. CLI installer)
        if self._row.install_steps:
            steps.extend(steps_from_defs(
                self._row.install_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        # MCP config steps - use inner HindsightMcpRecipe provision_steps
        mcp_fn = getattr(self._mcp, "provision_steps", None)
        if callable(mcp_fn):
            steps.extend(mcp_fn())  # type: ignore[misc]
        # Rule block steps
        rules_fn = getattr(self._rules, "provision_steps", None)
        if callable(rules_fn):
            steps.extend(rules_fn())  # type: ignore[misc]
        return steps

    def provision(self, context: dict[str, Any]) -> ProviderRecipeResult:
        owned: list[str] = []
        for op in (self.install, self.configure):
            result = op(context)
            owned.extend(result.artifacts_owned)
            if not result.success:
                return self._stamp(ProviderRecipeResult.fail(
                    f"provision failed: {result.error}",
                    details={**result.details, "artifacts_owned": owned},
                ))
        verified = self.verify(context)
        all_owned = [*owned, *verified.artifacts_owned]
        if not verified.success:
            return self._stamp(ProviderRecipeResult.fail(
                f"verify failed: {verified.error}",
                details={**verified.details, "artifacts_owned": all_owned},
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.VERIFIED,
            artifacts=all_owned,
            status="hybrid provisioned",
        ))

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        mcp_result = self._mcp.probe(context)
        rules_result = self._rules.probe(context)
        state = (
            RecipeState.VERIFIED
            if mcp_result.state is RecipeState.VERIFIED and rules_result.state is RecipeState.VERIFIED
            else RecipeState.ABSENT
        )
        return ProviderRecipeResult(
            success=mcp_result.success and rules_result.success,
            state=state,
            artifacts_owned=list(mcp_result.artifacts_owned) + list(rules_result.artifacts_owned),
            status=f"mcp: {mcp_result.status}; rules: {rules_result.status}",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        mcp_result = self._mcp.install(context)
        rules_result = self._rules.install(context)
        return ProviderRecipeResult(
            success=mcp_result.success and rules_result.success,
            state=RecipeState.INSTALLING,
            status="external backend + rules",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        sync = _sync_hindsight_mcp_entry(
            self.provider_id, self._project_root, self._mcp.backend
        )
        mcp_ok = bool(sync.get("ok"))
        mcp_status = "entry written (managed)" if mcp_ok else f"sync refused: {sync.get('collisions')}"
        mcp_artifacts = (
            [f"{sync.get('config_path')}::{self._mcp.backend.server_name}"] if mcp_ok else []
        )
        rules_result = self._rules.configure(context)
        return ProviderRecipeResult(
            success=mcp_ok and rules_result.success,
            state=RecipeState.CONFIGURING,
            artifacts_owned=mcp_artifacts + list(rules_result.artifacts_owned),
            status=f"mcp: {mcp_status}; rules: {rules_result.status}",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        mcp_result = self._mcp.verify(context)
        rules_result = self._rules.verify(context)
        return ProviderRecipeResult(
            success=mcp_result.success and rules_result.success,
            state=RecipeState.VERIFIED if (mcp_result.success and rules_result.success) else RecipeState.ABSENT,
            artifacts_owned=list(mcp_result.artifacts_owned) + list(rules_result.artifacts_owned),
            status=f"mcp: {mcp_result.status}; rules: {rules_result.status}",
            error=mcp_result.error or rules_result.error,
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        mcp_result = self._mcp.uninstall(context)
        rules_result = self._rules.uninstall(context)
        return ProviderRecipeResult(
            success=mcp_result.success and rules_result.success,
            state=RecipeState.ABSENT,
            status="external backend + rules",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        # Single removal path (see _McpConfigAdapter.prune): remove by name,
        # then clear the ownership record.
        mcp_result = self._mcp.prune(context)
        _sync_hindsight_mcp_entry(
            self.provider_id, self._project_root, self._mcp.backend, remove=True
        )
        rules_result = self._rules.prune(context)
        return ProviderRecipeResult(
            success=mcp_result.success and rules_result.success,
            state=RecipeState.ABSENT,
            status=f"mcp: {mcp_result.status}; rules: {rules_result.status}",
            error=mcp_result.error or rules_result.error,
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.VERIFIED,
            status="would configure mcp + rules (dry-run)",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def to_result(self, base) -> ProviderRecipeResult:
        return ProviderRecipeResult(
            success=base.success,
            state=base.state,
            artifacts_owned=list(base.artifacts_owned),
            status=base.status,
            error=base.error,
            details=dict(base.details),
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )



__all__ = [
    "GuidanceOnlyRecipe",
    "HINDSIGHT_MANAGED_ID",
    "HooksInstallerRecipe",
    "PluginConfigRecipe",
    "RULE_TEXT",
    "RulesOnlyRecipe",
]
