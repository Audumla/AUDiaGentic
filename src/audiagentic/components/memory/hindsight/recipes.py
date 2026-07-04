"""Hindsight implementation recipes with provider-facing strategy dispatch.

Registers Hindsight capability recipes per provider, using matrix data from this
implementation package. Each recipe strategy type dispatches to the appropriate
implementation. Hindsight-specific provider setup is contained here; the
providers component exposes only generic recipe interfaces.
"""
from __future__ import annotations

import logging
import shlex
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class HindsightStatusState(str, Enum):
    """Aggregate status for a provider's Hindsight integration.

    Distinct from RecipeState (per-recipe lifecycle state). This value summarizes
    whether the provider's Hindsight recipe set is active, inactive, or absent
    from the registry — useful for CLI/dashboard consumers that need a single
    machine-readable token rather than per-recipe details.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    NOT_REGISTERED = "not_registered"

from audiagentic.components.memory.hindsight.export import (
    HindsightBackendConfig,
    build_hindsight_backend,
)
from audiagentic.components.memory.hindsight.matrix import (
    HINDSIGHT_RECIPE_MATRIX,
    HindsightRecipeRow,
)
from audiagentic.components.memory.hindsight.mcp_recipe import (
    HindsightMcpRecipe,
    HindsightTarget,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.components.providers.services.recipes import (
    ProviderCapabilityRecipe,
    ProviderRecipeKind,
    ProviderRecipeRegistry,
    ProviderRecipeResult,
    RecipeState,
)
from audiagentic.foundation.descriptors import resolve_ref
from audiagentic.foundation.toolchains.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.managed_block import (
    apply_managed_block,
    block_artifact_id,
    remove_managed_block,
)
from audiagentic.foundation.toolchains.probes import CommandProbe
from audiagentic.foundation.toolchains.provision_steps import (
    CompensatingSequence,
    ManagedBlockStep,
    ProvisionStep,
    provision_step_from_dict,
)

_SHELL_METACHARS = ("|", "&&", ";", ">", "<")
RULE_TEXT = """Use Hindsight memory when prior project context may help.
- Recall before design/history questions or non-trivial work.
- Retain durable decisions, user preferences, architecture constraints, and outcomes.
- Do not retain secrets, credentials, or transient noise.
"""
_RULE_BLOCK_ID = "hindsight-memory"


def _command_parts(command: str) -> list[str]:
    """Return argv for a simple command, refusing shell compound syntax.

    Raises AudiaGenticError with code REC-ML-001 if the command contains
    shell compound operators. Callers should catch and log externally.
    """
    if any(token in command for token in _SHELL_METACHARS):
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        raise AudiaGenticError(
            code="REC-ML-001",
            kind="validation",
            message=(
                f"shell compound command requires structured shell-step support: {command!r}"
            ),
        )
    return shlex.split(command)


class _RowRecipe(ProviderCapabilityRecipe):
    """Common provider metadata + result re-stamping for Hindsight recipes.

    Extends ProviderCapabilityRecipe with Hindsight-specific provenance and
    action-guidance overlay drawn from a matrix row.
    """

    capability_id = "hindsight"
    backend_id: str | None = None

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

    def provision(self, context: dict[str, Any]) -> ProviderRecipeResult:
        """Hindsight-specific provision: probe → install → configure → verify."""
        probed = self.probe(context)
        if probed.success and probed.state is RecipeState.VERIFIED:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.VERIFIED, status="already provisioned",
            ))

        owned: list[str] = []
        for op in (self.install, self.configure):
            result = op(context)
            owned.extend(result.artifacts_owned)
            if not result.success:
                return self._stamp(ProviderRecipeResult.fail(
                    result.error or "provision failed",
                    state=result.state,
                    details={"artifacts_owned": owned},
                ))

        verified = self.verify(context)
        all_owned = [*owned, *verified.artifacts_owned]
        if not verified.success:
            return self._stamp(ProviderRecipeResult.fail(
                verified.error or "verify failed",
                state=RecipeState.ERROR,
                details={"artifacts_owned": all_owned},
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.VERIFIED, artifacts=all_owned, status="provisioned",
        ))

    def teardown(self, context: dict[str, Any]) -> ProviderRecipeResult:
        """Hindsight-specific teardown: prune → uninstall → verify absent."""
        pruned = self.prune(context)
        if not pruned.success:
            return pruned

        removed = self.uninstall(context)
        if not removed.success:
            return removed

        probed = self.probe(context)
        if probed.success and probed.state is RecipeState.ABSENT:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="removed",
            ))
        return self._stamp(ProviderRecipeResult.fail(
            "integration still present after teardown",
            action_needed=self._row.audia_action,
        ))


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
            probe = CommandProbe(tuple(_command_parts(cmd)), expect_exit=0, timeout=15)
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
        steps = _steps_from_defs(self._row.install_steps, params)
        seq_result = CompensatingSequence(steps).run(context)
        if seq_result.status == "ok":
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.INSTALLING, status="installer succeeded",
            ))
        return self._stamp(ProviderRecipeResult.fail(
            f"installer failed: {seq_result.reason or 'unknown'}",
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
        steps = _steps_from_defs(self._row.uninstall_steps, params)
        seq_result = CompensatingSequence(steps).run(context)
        if seq_result.status == "ok":
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="uninstaller succeeded",
            ))
        return self._stamp(ProviderRecipeResult.fail(
            f"uninstaller failed: {seq_result.reason or 'unknown'}",
        ))

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="hooks managed by CLI; no config to prune",
        ))

    def provision_steps(self) -> list[ProvisionStep]:
        params = _hindsight_params(self._backend)
        return _steps_from_defs(
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
            steps = _steps_from_defs(self._row.install_steps, params)
            seq_result = CompensatingSequence(steps).run(context)
            if seq_result.status != "ok":
                return self._stamp(ProviderRecipeResult.fail(
                    f"plugin install failed: {seq_result.reason or 'unknown'}",
                ))
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
            steps = _steps_from_defs(self._row.uninstall_steps, params)
            seq_result = CompensatingSequence(steps).run(context)
            if seq_result.status != "ok":
                return self._stamp(ProviderRecipeResult.fail(
                    f"plugin uninstall failed: {seq_result.reason or 'unknown'}",
                ))
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
            steps.extend(_steps_from_defs(
                self._row.install_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        if self._row.configure_steps:
            steps.extend(_steps_from_defs(
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
            steps.extend(_steps_from_defs(
                self._row.install_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        if self._row.configure_steps:
            steps.extend(_steps_from_defs(
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
            steps = _steps_from_defs(self._row.install_steps, params)
            seq_result = CompensatingSequence(steps).run(context)
            if seq_result.status != "ok":
                return self._stamp(ProviderRecipeResult.fail(
                    f"plugin install failed: {seq_result.reason or 'unknown'}",
                ))
        return self._stamp(ProviderRecipeResult.ok(RecipeState.INSTALLING, status="plugin installed"))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        import json
        import os
        if self._row.configure_steps:
            params = _hindsight_params(self._backend)
            config_path_for_steps = self._harness_config_path or self._url_config_path
            params["CONFIG_PATH"] = str(config_path_for_steps)
            steps = _steps_from_defs(
                self._row.configure_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            )
            seq_result = CompensatingSequence(steps).run(context)
            if seq_result.status != "ok":
                return self._stamp(ProviderRecipeResult.fail(
                    f"plugin configure failed: {seq_result.reason or 'unknown'}",
                ))
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
            steps = _steps_from_defs(self._row.uninstall_steps, params)
            seq_result = CompensatingSequence(steps).run(context)
            if seq_result.status != "ok":
                return self._stamp(ProviderRecipeResult.fail(
                    f"plugin uninstall failed: {seq_result.reason or 'unknown'}",
                ))
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
            return _steps_from_defs(
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
    """Replace brace-delimited placeholder tokens with backend values.

    Uses the same parameter mapping as _hindsight_params for consistency:
    URL, MCP_URL, TOKEN, KEY, ID.  Empty optional fields produce no replacement,
    so "{TOKEN}" remains literal when the backend has no api_key — callers that
    rely on those placeholders should check configuration first.
    """
    if not command:
        return command
    params = _hindsight_params(backend)
    for key, value in params.items():
        command = command.replace(f"{{{key}}}", value)
    return command


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


def _steps_from_defs(
    step_defs: list[dict[str, Any]],
    params: dict[str, str],
    *,
    recipe_id: str | None = None,
    registry: ArtifactRegistry | None = None,
) -> list[ProvisionStep]:
    """Build ProvisionStep instances from YAML step definitions."""
    steps: list[ProvisionStep] = []
    for i, defn in enumerate(step_defs):
        step_data = dict(defn)
        if "id" not in step_data:
            step_data["id"] = f"step-{i}"
        steps.append(
            provision_step_from_dict(
                step_data,
                params,
                registry=registry,
                recipe_id=recipe_id,
            )
        )
    return steps


def _normalize_platform(key: str) -> str:
    """Normalize a platform key to canonical form.

    Accepts aliases ('macos', 'darwin') → 'darwin', 'linux' → 'linux',
    ('win', 'windows', 'win32') → 'win'. Returns the lowercased key if no
    mapping applies, so an unknown constraint simply won't match any platform.
    """
    normalized = key.lower().strip()
    if normalized in ("macos", "darwin"):
        return "darwin"
    if normalized in ("linux",):
        return "linux"
    if normalized in ("win", "windows", "win32"):
        return "win"
    return normalized


def _platform_supported(row: HindsightRecipeRow) -> bool:
    """Check if the current platform is in the row's platform constraints.

    Constraints must be canonical keys: 'darwin', 'linux', or 'win'.
    Empty constraint list means supported on all platforms.
    """
    from audiagentic.foundation.toolchains import platform_key

    if not row.platform_constraints:
        return True
    current = platform_key()
    allowed = {_normalize_platform(c) for c in row.platform_constraints}
    return current in allowed


_INSTALLER_KINDS = (
    ProviderRecipeKind.HOOKS,
    ProviderRecipeKind.WRAPPER_CLI,
    ProviderRecipeKind.PLUGIN_CONFIG,
)


def _external_fallback_row(
    row: HindsightRecipeRow, provider_id: str, reason: str
) -> HindsightRecipeRow:
    """Downgrade an installer-style row so the provider points at the external
    Hindsight server without a local install: MCP config when the provider
    supports MCP, otherwise a rules-only block.
    """
    descriptor = get_descriptor(provider_id)
    if descriptor and descriptor.mcp_config:
        return HindsightRecipeRow(
            provider_id=provider_id,
            display_name=row.display_name,
            integration_type="fallback-mcp",
            recipe_kind=ProviderRecipeKind.MCP_CONFIG,
            source_url=row.source_url,
            source_date=row.source_date,
            source_status="unconfirmed",
            audia_action="manage_config_writes",
            notes=reason,
        )
    return HindsightRecipeRow(
        provider_id=provider_id,
        display_name=row.display_name,
        integration_type="rules-only",
        recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
        source_url=row.source_url,
        source_date=row.source_date,
        source_status="unconfirmed",
        audia_action="action_needed",
        notes=reason,
    )


def resolve_hindsight_strategy(
    provider_id: str,
    project_root: Path | None = None,
) -> HindsightRecipeRow | None:
    """Resolve the best Hindsight strategy for a provider.

    Precedence: verified native/installer > mcp-config > fallback-mcp > rules-only.
    Platform gate drops unsupported installer strategies and falls back to
    pointing at the external server via MCP/rules. Source gate is enforced by
    the builder.
    """
    rows = [row for row in HINDSIGHT_RECIPE_MATRIX if row.provider_id == provider_id]
    if not rows:
        return None

    row = rows[0]  # one row per provider

    if row.recipe_kind in _INSTALLER_KINDS and not _platform_supported(row):
        return _external_fallback_row(
            row, provider_id,
            f"platform-gated ({', '.join(row.platform_constraints)}); external fallback",
        )

    return row


def _build_hooks_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
) -> Any:
    """Build HooksInstallerRecipe with source gate."""
    if row.source_status != "verified":
        return GuidanceOnlyRecipe(row)
    return HooksInstallerRecipe(row, backend)


def _build_plugin_url_config_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    url_config_path: str | Path,
    harness_config_path: str | Path | None = None,
) -> Any:
    """Build Plugin URL config recipe with optional Windows repair."""
    return _PluginUrlConfigRecipe(
        row, backend, url_config_path,
        harness_config_path=harness_config_path,
    )


def _build_plugin_config_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None,
) -> Any:
    """Build plugin config recipe from metadata.

    Prefers plugin_array > url_config_path > generic MCP target fallback.
    Source gate applies only when install_steps are present and unverified.
    """
    harness_path = _resolve_harness_config_path(provider_id, project_root)
    if row.source_status != "verified" and row.install_steps:
        return GuidanceOnlyRecipe(row)
    if row.plugin_array_package and harness_path:
        return _PluginArrayRecipe(row, backend, harness_path)
    if row.plugin_url_config_path:
        return _build_plugin_url_config_recipe(
            row, backend, row.plugin_url_config_path,
            harness_path or row.plugin_url_config_path,
        )
    if harness_path:
        descriptor = get_descriptor(provider_id)
        spec = descriptor.mcp_config if descriptor else None
        target = HindsightTarget(
            config_path=harness_path,
            writer_fn=spec.writer if spec else None,
            reader_fn=spec.reader if spec else None,
            remover_fn=spec.remover if spec else None,
        )
        return PluginConfigRecipe(row, backend, target)
    return GuidanceOnlyRecipe(row)


def _build_mcp_config_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None,
) -> Any:
    """Build MCP-config recipe.

    Blocked source status returns guidance-only. Otherwise dispatches to
    _build_mcp_recipe for inner composition (MCP + rules).
    """
    if row.source_status == "blocked":
        return GuidanceOnlyRecipe(row)
    harness_path = _resolve_harness_config_path(provider_id, project_root)
    rule_path = _resolve_rule_path(provider_id, project_root)
    return _build_mcp_recipe(
        row, backend, provider_id, project_root, harness_path, rule_path,
    )


def _build_guidance_only_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None,
) -> Any:
    """Build guidance-only recipe with rules fallback."""
    rule_path = _resolve_rule_path(provider_id, project_root)
    if rule_path:
        return RulesOnlyRecipe(row, rule_path, project_root=project_root)
    return GuidanceOnlyRecipe(row)


# Factory registry keyed by ProviderRecipeKind.
# Each entry is a callable that accepts (row, backend, provider_id, project_root)
# and returns a recipe instance.
_RecipeFactory = Callable[
    [HindsightRecipeRow, HindsightBackendConfig, str, Path | None], Any
]

_RECIPE_FACTORIES: dict[ProviderRecipeKind, _RecipeFactory] = {
    ProviderRecipeKind.HOOKS: lambda r, b, p, pr: _build_hooks_recipe(r, b),
    ProviderRecipeKind.WRAPPER_CLI: lambda r, b, p, pr: _build_hooks_recipe(r, b),
    ProviderRecipeKind.PLUGIN_CONFIG: _build_plugin_config_recipe,
    ProviderRecipeKind.MCP_CONFIG: _build_mcp_config_recipe,
    ProviderRecipeKind.HYBRID: _build_mcp_config_recipe,
    ProviderRecipeKind.GUIDANCE_ONLY: _build_guidance_only_recipe,
}


def build_hindsight_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None = None,
) -> Any:
    """Build a recipe object for a resolved Hindsight strategy row.

    Dispatches through _RECIPE_FACTORIES keyed by ProviderRecipeKind.
    Unknown kinds fall back to GuidanceOnlyRecipe (intentional default).
    """
    factory = _RECIPE_FACTORIES.get(row.recipe_kind)
    if factory is not None:
        return factory(row, backend, provider_id, project_root)
    return GuidanceOnlyRecipe(row)


def _build_mcp_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None,
    harness_path: str | None,
    rule_path: Path | None,
) -> Any:
    """Build MCP-config recipe for MCP_CONFIG or HYBRID kind.

    When HYBRID and rule_path exists, wraps in _CompositeRecipe with rules layer.
    Falls back to rules-only or guidance when paths are unavailable.
    """
    if harness_path:
        descriptor = get_descriptor(provider_id)
        spec = descriptor.mcp_config if descriptor else None

        target = HindsightTarget(
            config_path=harness_path,
            writer_fn=spec.writer if spec else None,
            reader_fn=spec.reader if spec else None,
            remover_fn=spec.remover if spec else None,
        )
        registry = ArtifactRegistry(project_root) if project_root else None
        inner = HindsightMcpRecipe(
            backend,
            target,
            registry=registry,
            recipe_id=f"hindsight:{provider_id}:mcp",
        )

        if row.recipe_kind == ProviderRecipeKind.HYBRID and rule_path:
            rules = RulesOnlyRecipe(row, rule_path, project_root=project_root)
            return _CompositeRecipe(row, inner, rules)
        return _McpConfigAdapter(row, inner)
    if rule_path:
        return RulesOnlyRecipe(row, rule_path, project_root=project_root)
    return GuidanceOnlyRecipe(row)


def _resolve_harness_config_path(provider_id: str, project_root: Path | None = None) -> str | None:
    """Resolve the real harness config path for a provider from its descriptor.

    The path is anchored to ``project_root`` so provisioning writes inside the
    target project, never relative to the current working directory.
    """
    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        return None
    spec = descriptor.mcp_config
    if spec is None:
        return None
    config_path = spec.config_path
    resolved = config_path(project_root) if callable(config_path) else config_path
    if resolved is None:
        return None
    return str(_absolute_project_path(resolved, Path(project_root) if project_root else None))


def _absolute_project_path(path: str | Path, project_root: Path | None = None) -> Path:
    target = Path(path).expanduser()
    if target.is_absolute() or project_root is None:
        return target
    return Path(project_root) / target


def _resolve_rule_path(provider_id: str, project_root: Path | None = None) -> Path | None:
    """Resolve a provider instruction/rules file from generic descriptor metadata."""
    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        return None
    rel_path = descriptor.instruction_file
    if rel_path is None:
        for agent_file in descriptor.agent_files:
            if agent_file.managed and agent_file.rel_path.lower().endswith((".md", ".mdx")):
                rel_path = agent_file.rel_path
                break
    if rel_path is None:
        return None
    return _absolute_project_path(rel_path, Path(project_root) if project_root else None)


def register_hindsight_recipes(
    registry: ProviderRecipeRegistry,
    backend: HindsightBackendConfig | None = None,
    project_root: Path | None = None,
) -> list[Any]:
    """Register Hindsight recipes for providers that have matrix rows.

    Uses resolve_hindsight_strategy + build_hindsight_recipe for each provider.
    Applies platform gate and source gate automatically.
    Returns the list of registered recipes.
    """
    if backend is None and project_root:
        backend = build_hindsight_backend(project_root)

    registered: list[Any] = []

    for row in HINDSIGHT_RECIPE_MATRIX:
        resolved = resolve_hindsight_strategy(row.provider_id, project_root)
        if resolved is None:
            continue

        if not backend:
            recipe = GuidanceOnlyRecipe(resolved)
        else:
            recipe = build_hindsight_recipe(resolved, backend, resolved.provider_id, project_root)

        registry.register(recipe)
        registered.append(recipe)

    return registered


def _reconcile(
    project_root: Path,
    operation: str,
    *,
    backend: HindsightBackendConfig | None = None,
    provider_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, ProviderRecipeResult]:
    """Central registry setup + dispatch for apply/teardown/prune operations.

    ``operation`` is one of: 'install', 'uninstall', 'prune'.
    For install/uninstall the registry lifecycle (probe → ops → verify) runs via
    ``_RowRecipe.provision/teardown``.  For prune only the prune primitive runs
    to avoid executing command-based uninstallers on stale config.
    """
    registry = ProviderRecipeRegistry()
    recipes = register_hindsight_recipes(
        registry,
        backend=backend,
        project_root=project_root,
    )
    selected = set(provider_ids) if provider_ids is not None else None
    ctx = context or {}
    results: dict[str, ProviderRecipeResult] = {}
    for recipe in recipes:
        if selected is not None and recipe.provider_id not in selected:
            continue
        if operation == "prune":
            results[recipe.provider_id] = recipe.prune(ctx)
        elif operation == "uninstall":
            result = registry.uninstall(
                recipe.provider_id, recipe.capability_id, recipe.backend_id, ctx
            )
            results[recipe.provider_id] = result if result else ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="nothing to uninstall",
            )
        else:  # install
            result = registry.install(
                recipe.provider_id, recipe.capability_id, recipe.backend_id, ctx
            )
            results[recipe.provider_id] = result if result else ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="nothing to install",
            )
    return results


def apply_hindsight(
    project_root: Path,
    *,
    backend: HindsightBackendConfig | None = None,
    provider_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, ProviderRecipeResult]:
    """Provision Hindsight recipes from the contained memory implementation."""
    return _reconcile(
        project_root, "install",
        backend=backend, provider_ids=provider_ids, context=context,
    )


def teardown_hindsight(
    project_root: Path,
    *,
    backend: HindsightBackendConfig | None = None,
    provider_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, ProviderRecipeResult]:
    """Remove Hindsight artifacts managed by the contained memory implementation."""
    return _reconcile(
        project_root, "uninstall",
        backend=backend, provider_ids=provider_ids, context=context,
    )


def prune_hindsight(
    project_root: Path,
    *,
    backend: HindsightBackendConfig | None = None,
    provider_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, ProviderRecipeResult]:
    """Remove only Hindsight *config* artifacts (MCP entries, rule blocks).

    Unlike :func:`teardown_hindsight`, this runs each recipe's ``prune`` only —
    never a command-based uninstaller. It is safe and idempotent, used to clear
    stale config from providers that are no longer enabled without executing
    destructive package uninstalls that may never have installed anything.
    """
    return _reconcile(
        project_root, "prune",
        backend=backend, provider_ids=provider_ids, context=context,
    )


class _McpConfigAdapter(_RowRecipe):
    """Thin adapter that wraps HindsightMcpRecipe with provider metadata.

    Every lifecycle call delegates to the inner recipe and re-stamps the
    result with this provider's provenance via ``_stamp``.
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        inner: HindsightMcpRecipe,
    ) -> None:
        super().__init__(row)
        self._inner = inner

    def provision_steps(self) -> list[ProvisionStep]:
        params = _hindsight_params(self._inner.backend)
        steps: list[ProvisionStep] = []
        # Row-level install/uninstall steps from matrix (e.g. pip install + init)
        if self._row.install_steps:
            steps.extend(_steps_from_defs(
                self._row.install_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        # Row-level configure steps (e.g. config-set for plugin arrays)
        if self._row.configure_steps:
            steps.extend(_steps_from_defs(
                self._row.configure_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        # Inner MCP config steps (only for JSON-based configs without callbacks)
        inner_fn = getattr(self._inner, "provision_steps", None)
        if callable(inner_fn):
            steps.extend(inner_fn())  # type: ignore[misc]
        return steps

    def provision(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(self._inner.provision(context))

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(self._inner.probe(context))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(self._inner.install(context))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(self._inner.configure(context))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(self._inner.verify(context))

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(self._inner.uninstall(context))

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(self._inner.prune(context))

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
    """Wraps an MCP config recipe and a rules recipe, executing both in sequence."""

    def __init__(
        self,
        row: HindsightRecipeRow,
        mcp_inner: HindsightMcpRecipe,
        rules_inner: RulesOnlyRecipe,
    ) -> None:
        super().__init__(row)
        self._mcp = mcp_inner
        self._rules = rules_inner

    def provision_steps(self) -> list[ProvisionStep]:
        backend = self._mcp.backend
        params = _hindsight_params(backend)
        steps: list[ProvisionStep] = []
        # Row-level install steps first (e.g. CLI installer)
        if self._row.install_steps:
            steps.extend(_steps_from_defs(
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
        mcp_result = self._mcp.configure(context)
        rules_result = self._rules.configure(context)
        return ProviderRecipeResult(
            success=mcp_result.success and rules_result.success,
            state=RecipeState.CONFIGURING,
            artifacts_owned=list(mcp_result.artifacts_owned) + list(rules_result.artifacts_owned),
            status=f"mcp: {mcp_result.status}; rules: {rules_result.status}",
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
        mcp_result = self._mcp.prune(context)
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


def build_hindsight_status(
    registry: ProviderRecipeRegistry,
    provider_id: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build Hindsight status for a specific provider from the recipe registry."""
    recipes = registry.list_for_provider(provider_id, "hindsight")
    if not recipes:
        return {
            "provider_id": provider_id,
            "hindsight": {
                "status": HindsightStatusState.NOT_REGISTERED.value,
                "action_needed": "no Hindsight recipe for this provider",
            },
        }

    results = []
    for recipe in recipes:
        status = registry.status(
            recipe.provider_id,
            recipe.capability_id,
            recipe.backend_id,
            context,
        )
        if status is not None:
            row = getattr(recipe, "_row", None)
            source_status = getattr(row, "source_status", "") or "unconfirmed"
            results.append({
                "provider_id": recipe.provider_id,
                "capability_id": recipe.capability_id,
                "kind": recipe.recipe_kind.value,
                "state": status.state.value,
                "status": status.status,
                "action_needed": getattr(status, "action_needed", ""),
                "source_url": getattr(status, "source_url", ""),
                "source_date": getattr(status, "source_date", ""),
                "source_status": source_status,
                "artifacts_owned": list(getattr(status, "artifacts_owned", [])),
            })

    is_active = any(r["state"] == RecipeState.VERIFIED.value for r in results)
    return {
        "provider_id": provider_id,
        "hindsight": {
            "status": HindsightStatusState.ACTIVE.value if is_active else HindsightStatusState.INACTIVE.value,
            "recipes": results,
        },
    }


__all__ = [
    "GuidanceOnlyRecipe",
    "HooksInstallerRecipe",
    "HindsightStatusState",
    "PluginConfigRecipe",
    "RULE_TEXT",
    "RulesOnlyRecipe",
    "apply_hindsight",
    "build_hindsight_status",
    "register_hindsight_recipes",
    "teardown_hindsight",
]
