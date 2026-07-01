"""Hindsight implementation recipes with provider-facing strategy dispatch.

Registers Hindsight capability recipes per provider, using matrix data from this
implementation package. Each recipe strategy type dispatches to the appropriate
implementation. Hindsight-specific provider setup is contained here; the
providers component exposes only generic recipe interfaces.
"""
from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.matrix import (
    HINDSIGHT_RECIPE_MATRIX,
    HindsightRecipeRow,
)
from audiagentic.components.memory.hindsight.mcp_recipe import (
    HindsightMcpRecipe,
    HindsightTarget,
)
from audiagentic.components.memory.hindsight_export import (
    HindsightBackendConfig,
    build_hindsight_backend,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.components.providers.services.recipes import (
    ProviderRecipeKind,
    ProviderRecipeRegistry,
    ProviderRecipeResult,
    RecipeState,
)
from audiagentic.foundation.toolchains.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.managed_block import (
    apply_managed_block,
    block_artifact_id,
    remove_managed_block,
)
from audiagentic.foundation.toolchains.probes import CommandProbe
from audiagentic.foundation.workflow.invocation.models import StepResult
from audiagentic.foundation.workflow.invocation.steps import SequenceStep, ShellStep

_SHELL_METACHARS = ("|", "&&", ";", ">", "<")
RULE_TEXT = """Use Hindsight memory when prior project context may help.
- Recall before design/history questions or non-trivial work.
- Retain durable decisions, user preferences, architecture constraints, and outcomes.
- Do not retain secrets, credentials, or transient noise.
"""
_RULE_BLOCK_ID = "hindsight-memory"


def _command_parts(command: str) -> list[str]:
    """Return argv for a simple command, refusing shell compound syntax."""
    if any(token in command for token in _SHELL_METACHARS):
        raise ValueError(
            "shell compound command requires structured shell-step support"
        )
    return shlex.split(command)


def _step_detail(result: StepResult) -> str:
    """Extract a human-readable failure detail from a SequenceStep result."""
    if result.reason:
        return result.reason
    outputs = result.outputs if isinstance(result.outputs, dict) else {}
    for value in outputs.values():
        if isinstance(value, dict) and value.get("returncode") not in (0, None):
            return (value.get("stdout") or "").strip() or "command failed"
    return "command failed"


def _run_command(
    command: str,
    backend: HindsightBackendConfig,
    *,
    timeout: int = 300,
) -> tuple[bool, str]:
    """Run an installer/uninstaller command via the toolchain step machinery.

    The matrix joins multiple steps with ``&&`` (e.g.
    ``pip install hindsight-X && hindsight-X install --api-url URL``). Each
    ``&&`` segment becomes a :class:`ShellStep` (argv) and they run in order via
    a :class:`SequenceStep`, after placeholder substitution (URL/TOKEN/KEY/ID).

    Commands containing ``|`` (e.g. ``curl … | bash``) cannot be split into
    argv and are run via the system shell instead. Returns ``(ok, detail)``.
    """
    import subprocess

    rendered = _parameterize_command(command, backend)

    if "|" in rendered:
        result = subprocess.run(
            rendered,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout or "command failed").strip()

    segments = [seg.strip() for seg in rendered.split("&&") if seg.strip()]
    if not segments:
        return False, "empty command"

    steps: list[ShellStep] = []
    for index, segment in enumerate(segments):
        if any(tok in segment for tok in (";", ">", "<")):
            return False, f"unsupported shell syntax: {segment!r}"
        steps.append(ShellStep(id=f"step{index}", command=tuple(shlex.split(segment)), timeout=timeout))

    result = SequenceStep(id="install", steps=tuple(steps)).run({})
    if result.status == "ok":
        return True, ""
    return False, _step_detail(result)


class _RowRecipe:
    """Common provider metadata + result re-stamping for Hindsight recipes.

    Carries the per-provider identity (provider_id, capability, recipe kind,
    source provenance) drawn from a matrix row, and provides ``_stamp`` to
    overlay that provenance onto a delegated inner-recipe result.
    """

    capability_id = "hindsight"
    backend_id: str | None = None

    def __init__(
        self,
        row: HindsightRecipeRow,
        *,
        recipe_kind: ProviderRecipeKind | None = None,
    ) -> None:
        self.provider_id = row.provider_id
        self.recipe_kind = recipe_kind if recipe_kind is not None else row.recipe_kind
        self.display_name = row.display_name
        self.source_url = row.source_url
        self.source_date = row.source_date
        self._row = row

    def _stamp(self, result: Any) -> ProviderRecipeResult:
        """Re-stamp any recipe result with this provider's provenance.

        Accepts both the foundation ``RecipeResult`` (returned by inner MCP
        recipes) and ``ProviderRecipeResult``; reads fields by duck-typing. A
        result that already carries its own ``action_needed`` (e.g. a
        notes-preferred message) keeps it; otherwise the row's default action
        guidance is applied.
        """
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
            return self._stamp(ProviderRecipeResult.fail(str(exc)))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.source_status != "verified":
            return self._stamp(ProviderRecipeResult.fail(
                f"installer source {self._row.source_status}; refusing to execute",
                action_needed=self._row.notes or self._row.audia_action,
            ))
        if not self._row.install_command:
            return self._stamp(ProviderRecipeResult.fail(
                "no install command for this provider",
            ))
        ok, detail = _run_command(self._row.install_command, self._backend)
        if ok:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.INSTALLING, status="installer command succeeded",
            ))
        return self._stamp(ProviderRecipeResult.fail(f"installer failed: {detail}"))

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
        if not self._row.uninstall_command:
            return self._stamp(ProviderRecipeResult.fail(
                "no uninstall command for this provider",
            ))
        ok, detail = _run_command(self._row.uninstall_command, self._backend)
        if ok:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="uninstaller command succeeded",
            ))
        return self._stamp(ProviderRecipeResult.fail(f"uninstaller failed: {detail}"))

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="hooks managed by CLI; no config to prune",
        ))

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status=f"would run: {self._row.install_command} (dry-run)",
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
        if self._row.install_command and self._should_run_plugin_command():
            if self._row.source_status != "verified":
                return self._stamp(ProviderRecipeResult.fail(
                    f"plugin installer source {self._row.source_status}; refusing to execute",
                    action_needed=self._row.notes or self._row.audia_action,
                ))
            ok, detail = _run_command(self._row.install_command, self._backend)
            if not ok:
                return self._stamp(ProviderRecipeResult.fail(
                    f"plugin install failed: {detail}",
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
        if self._row.uninstall_command and self._should_run_plugin_command():
            if self._row.source_status != "verified":
                return self._stamp(ProviderRecipeResult.ok(
                    RecipeState.ABSENT,
                    status=f"source {self._row.source_status}; no plugin installer was executed",
                    action_needed=self._row.notes or self._row.audia_action,
                ))
            ok, detail = _run_command(self._row.uninstall_command, self._backend)
            if not ok:
                return self._stamp(ProviderRecipeResult.fail(
                    f"plugin uninstall failed: {detail}",
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

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="would install plugin (dry-run)",
        ))


def _repair_windows_plugin_mcp(_backend: HindsightBackendConfig) -> tuple[bool, str]:
    """On Windows, patch the installed hindsight plugin's .mcp.json to use python.exe.

    The official plugin ships a bash launcher (run_mcp.sh) that fails when Git Bash
    is absent. This function locates the plugin cache .mcp.json and rewrites the
    hindsight server entry to invoke mcp_server.py via the plugin venv's python.exe.
    Idempotent — if already using python.exe the file is left untouched.
    """
    import glob
    import json
    import os

    home = Path.home()
    cache_pattern = str(
        home / ".claude" / "plugins" / "cache" / "hindsight" / "hindsight-memory" / "*" / ".mcp.json"
    )
    mcp_files = glob.glob(cache_pattern)
    if not mcp_files:
        return False, "hindsight plugin not installed (no .mcp.json in cache)"

    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return False, "APPDATA not set; cannot locate plugin data dir"
    data_dir = Path(appdata) / "Claude" / "plugins" / "data" / "hindsight-memory"
    venv_python = data_dir / "venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        return False, f"plugin venv not found at {venv_python}; run 'claude plugin install hindsight-memory' first"

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
        mcp_script = plugin_dir / "scripts" / "mcp_server.py"
        if not mcp_script.exists():
            continue
        servers["hindsight"] = {
            "command": str(venv_python),
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


class _ClaudePluginUrlRecipe(_RowRecipe):
    """Plugin-url recipe for Claude Code: writes hindsight API URL to plugin config.

    The Claude Code hindsight plugin reads its server URL from
    ~/.hindsight/claude-code.json as {"hindsightApiUrl": "<url>"} — a separate
    file from the MCP JSON format used by AUDiaGentic's own servers. The URL
    must come from HindsightBackendConfig, never hardcoded.

    On Windows, configure also patches the plugin's auto-generated .mcp.json
    to use python.exe instead of bash (the plugin ships a bash launcher that
    fails when Git Bash is absent).
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        backend: HindsightBackendConfig,
        url_config_path: str | Path,
    ) -> None:
        super().__init__(row)
        self._backend = backend
        self._url_config_path = Path(url_config_path).expanduser()

    def _current_url(self) -> str | None:
        try:
            import json
            data = json.loads(self._url_config_path.read_text(encoding="utf-8"))
            return data.get("hindsightApiUrl")
        except (OSError, ValueError):
            return None

    def _should_run_plugin_command(self) -> bool:
        return self._row.audia_action == "call_official_installer"

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._current_url() == self._backend.base_url:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.VERIFIED,
                artifacts=[str(self._url_config_path)],
                status="plugin URL config correct",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="plugin URL config absent or stale",
        ))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.install_command and self._should_run_plugin_command():
            if self._row.source_status != "verified":
                return self._stamp(ProviderRecipeResult.fail(
                    f"plugin installer source {self._row.source_status}; refusing to execute",
                    action_needed=self._row.notes or self._row.audia_action,
                ))
            ok, detail = _run_command(self._row.install_command, self._backend)
            if not ok:
                return self._stamp(ProviderRecipeResult.fail(f"plugin install failed: {detail}"))
        return self._stamp(ProviderRecipeResult.ok(RecipeState.INSTALLING, status="plugin installed"))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        import json
        import os
        self._url_config_path.parent.mkdir(parents=True, exist_ok=True)
        self._url_config_path.write_text(
            json.dumps({"hindsightApiUrl": self._backend.base_url}, indent=2),
            encoding="utf-8",
        )
        artifacts = [str(self._url_config_path)]
        if os.name == "nt":
            ok, detail = _repair_windows_plugin_mcp(self._backend)
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
        if self._row.uninstall_command and self._should_run_plugin_command():
            if self._row.source_status != "verified":
                return self._stamp(ProviderRecipeResult.ok(
                    RecipeState.ABSENT,
                    status=f"source {self._row.source_status}; no plugin installer was executed",
                    action_needed=self._row.notes or self._row.audia_action,
                ))
            ok, detail = _run_command(self._row.uninstall_command, self._backend)
            if not ok:
                return self._stamp(ProviderRecipeResult.fail(f"plugin uninstall failed: {detail}"))
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
    """Replace placeholder tokens in install/uninstall/status commands with backend values.

    Supported placeholders:
      URL    → backend.base_url
      TOKEN  → backend.api_key
      KEY    → backend.api_key
      ID     → backend.bank_id
    """
    if not command:
        return command
    replacements = [
        ("URL", backend.base_url),
    ]
    if backend.api_key:
        replacements.extend([
            ("TOKEN", backend.api_key),
            ("KEY", backend.api_key),
        ])
    if backend.bank_id:
        replacements.append(("ID", backend.bank_id))
    for placeholder, value in replacements:
        command = command.replace(placeholder, value)
    return command


def _platform_supported(row: HindsightRecipeRow) -> bool:
    """Check if the current platform is in the row's platform constraints.

    Uses the canonical platform_key() from foundation.toolchains.
    """
    if not row.platform_constraints:
        return True
    from audiagentic.foundation.toolchains import platform_key
    current = platform_key()
    for constraint in row.platform_constraints:
        constraint_lower = constraint.lower()
        if "macos" in constraint_lower or "darwin" in constraint_lower:
            if current == "darwin":
                return True
        elif "linux" in constraint_lower:
            if current == "linux":
                return True
        elif "win" in constraint_lower:
            if current == "win":
                return True
    return False


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


def build_hindsight_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None = None,
) -> Any:
    """Build a recipe object for a resolved Hindsight strategy row.

    Source gate: refuses to build executable recipes for native-installer/
    launch-wrapper when source_status is not 'verified'.
    """
    harness_path = _resolve_harness_config_path(provider_id, project_root)
    rule_path = _resolve_rule_path(provider_id, project_root)

    # Source gate for native/launch-wrapper
    if row.recipe_kind in (ProviderRecipeKind.HOOKS, ProviderRecipeKind.WRAPPER_CLI):
        if row.source_status != "verified":
            return GuidanceOnlyRecipe(row)
        return HooksInstallerRecipe(row, backend)

    if row.recipe_kind == ProviderRecipeKind.PLUGIN_CONFIG:
        if row.source_status != "verified" and row.install_command:
            return GuidanceOnlyRecipe(row)
        if row.plugin_url_config_path:
            return _ClaudePluginUrlRecipe(row, backend, row.plugin_url_config_path)
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

    if row.recipe_kind in (ProviderRecipeKind.MCP_CONFIG, ProviderRecipeKind.HYBRID):
        # Source gate: blocked/unverified rows should not execute MCP recipes
        if row.source_status == "blocked":
            return GuidanceOnlyRecipe(row)

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

            # HYBRID: composite MCP config + rule block when both paths exist
            if row.recipe_kind == ProviderRecipeKind.HYBRID and rule_path:
                rules = RulesOnlyRecipe(row, rule_path, project_root=project_root)
                return _CompositeRecipe(row, inner, rules)
            return _McpConfigAdapter(row, inner)
        if rule_path:
            return RulesOnlyRecipe(row, rule_path, project_root=project_root)
        return GuidanceOnlyRecipe(row)

    if row.recipe_kind == ProviderRecipeKind.GUIDANCE_ONLY:
        if rule_path:
            return RulesOnlyRecipe(row, rule_path, project_root=project_root)
        return GuidanceOnlyRecipe(row)

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


def _run_provision(recipe: Any, context: dict[str, Any]) -> ProviderRecipeResult:
    if hasattr(recipe, "provision"):
        result = recipe.provision(context)
        return recipe.to_result(result) if hasattr(recipe, "to_result") else result

    owned: list[str] = []
    probed = recipe.probe(context)
    if probed.success and probed.state is RecipeState.VERIFIED:
        return probed
    for operation in (recipe.install, recipe.configure):
        result = operation(context)
        owned.extend(result.artifacts_owned)
        if not result.success:
            return ProviderRecipeResult(
                success=result.success,
                state=result.state,
                artifacts_owned=owned,
                status=result.status,
                error=result.error,
                details=dict(result.details),
                source_url=result.source_url,
                source_date=result.source_date,
                action_needed=result.action_needed,
            )
    verified = recipe.verify(context)
    return ProviderRecipeResult(
        success=verified.success,
        state=verified.state,
        artifacts_owned=[*owned, *verified.artifacts_owned],
        status=verified.status,
        error=verified.error,
        details=dict(verified.details),
        source_url=verified.source_url,
        source_date=verified.source_date,
        action_needed=verified.action_needed,
    )


def _run_teardown(recipe: Any, context: dict[str, Any]) -> ProviderRecipeResult:
    if hasattr(recipe, "teardown"):
        result = recipe.teardown(context)
        return recipe.to_result(result) if hasattr(recipe, "to_result") else result

    for operation in (recipe.prune, recipe.uninstall):
        result = operation(context)
        if not result.success:
            return result
    probed = recipe.probe(context)
    if probed.success and probed.state is RecipeState.ABSENT:
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="removed",
            source_url=getattr(recipe, "source_url", ""),
            source_date=getattr(recipe, "source_date", ""),
        )
    row = getattr(recipe, "_row", None)
    return ProviderRecipeResult.fail(
        "integration still present after teardown",
        source_url=getattr(recipe, "source_url", ""),
        action_needed=row.audia_action if row else "",
    )


def apply_hindsight(
    project_root: Path,
    *,
    backend: HindsightBackendConfig | None = None,
    provider_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, ProviderRecipeResult]:
    """Provision Hindsight recipes from the contained memory implementation."""
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
        results[recipe.provider_id] = _run_provision(recipe, ctx)
    return results


def teardown_hindsight(
    project_root: Path,
    *,
    backend: HindsightBackendConfig | None = None,
    provider_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, ProviderRecipeResult]:
    """Remove Hindsight artifacts managed by the contained memory implementation."""
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
        results[recipe.provider_id] = _run_teardown(recipe, ctx)
    return results


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
        results[recipe.provider_id] = recipe.prune(ctx)
    return results


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
                "status": "not_registered",
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
            results.append({
                "provider_id": recipe.provider_id,
                "capability_id": recipe.capability_id,
                "kind": recipe.recipe_kind.value,
                "state": status.state.value,
                "status": status.status,
                "action_needed": status.action_needed,
                "source_url": status.source_url,
            })

    return {
        "provider_id": provider_id,
        "hindsight": {
            "status": "active" if any(r["state"] == "verified" for r in results) else "inactive",
            "recipes": results,
        },
    }


__all__ = [
    "GuidanceOnlyRecipe",
    "HooksInstallerRecipe",
    "PluginConfigRecipe",
    "RULE_TEXT",
    "RulesOnlyRecipe",
    "apply_hindsight",
    "build_hindsight_status",
    "register_hindsight_recipes",
    "teardown_hindsight",
]
