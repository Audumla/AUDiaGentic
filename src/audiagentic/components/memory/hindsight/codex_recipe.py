"""Codex Hindsight hook provisioning.

The official Codex installer is a bash script. On Windows, ``bash`` is often
the WSL shim, which writes into the Linux home directory and emits POSIX hook
commands. This recipe mirrors the documented installer artifacts with native
Python file writes so Codex gets usable hooks on every OS.
"""
from __future__ import annotations

import json
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
from audiagentic.components.memory.hindsight.recipes import _RowRecipe
from audiagentic.components.providers.services.recipes import (
    ProviderRecipeKind,
    ProviderRecipeResult,
)
from audiagentic.foundation.toolchains.recipe_contract import RecipeResult, RecipeState

_RAW_BASE = "https://raw.githubusercontent.com/vectorize-io/hindsight/main/hindsight-integrations/codex"
_SCRIPT_FILES = (
    "scripts/session_start.py",
    "scripts/recall.py",
    "scripts/retain.py",
    "scripts/lib/__init__.py",
    "scripts/lib/bank.py",
    "scripts/lib/client.py",
    "scripts/lib/config.py",
    "scripts/lib/content.py",
    "scripts/lib/daemon.py",
    "scripts/lib/llm.py",
    "scripts/lib/state.py",
)


def _home() -> Path:
    return Path.home()


def _quote_command_part(value: Path | str) -> str:
    text = str(value)
    return '"' + text.replace('"', '\\"') + '"'


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _codex_hooks_enabled(config_path: Path) -> bool:
    text = _read_text(config_path)
    in_features = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_features = line == "[features]"
            continue
        if in_features and line.startswith("codex_hooks"):
            return line.split("=", 1)[-1].strip().lower() == "true"
    return False


# RS18/RS06: intentional one-off — surgical TOML editing to upsert [features] section.
# Not expressible via WriteFileStep because the file is not owned by this recipe
# (shared with other codex settings); only a single key must be patched, not rewritten.
def _enable_codex_hooks(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    text = _read_text(config_path)
    lines = text.splitlines()
    if not lines:
        config_path.write_text("[features]\ncodex_hooks = true\n", encoding="utf-8")
        return

    out: list[str] = []
    in_features = False
    saw_features = False
    wrote = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_features and not wrote:
                out.append("codex_hooks = true")
                wrote = True
            in_features = stripped == "[features]"
            saw_features = saw_features or in_features
            out.append(raw)
            continue
        if in_features and stripped.startswith("codex_hooks"):
            out.append("codex_hooks = true")
            wrote = True
            continue
        out.append(raw)

    if saw_features and in_features and not wrote:
        out.append("codex_hooks = true")
        wrote = True
    if not saw_features:
        if out and out[-1].strip():
            out.append("")
        out.extend(["[features]", "codex_hooks = true"])
    config_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed official source
        dest.write_bytes(response.read())


class CodexHindsightRecipe(_RowRecipe):
    """Install and verify Hindsight's Codex hook integration."""

    recipe_kind = ProviderRecipeKind.HOOKS

    def __init__(self, row: HindsightRecipeRow, backend: HindsightBackendConfig) -> None:
        super().__init__(row)
        self._backend = backend
        self._install_dir = _home() / ".hindsight" / "codex"
        self._scripts_dir = self._install_dir / "scripts"
        self._user_config = _home() / ".hindsight" / "codex.json"
        self._codex_dir = _home() / ".codex"
        self._hooks_file = self._codex_dir / "hooks.json"
        self._config_file = self._codex_dir / "config.toml"

    def _artifacts(self) -> list[str]:
        return [
            str(self._user_config),
            str(self._hooks_file),
            str(self._config_file),
            str(self._scripts_dir),
        ]

    def _expected_hook_command(self, script_name: str) -> str:
        return f"{_quote_command_part(Path(sys.executable))} {_quote_command_part(self._scripts_dir / script_name)}"

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        missing = [
            path for path in (
                self._user_config,
                self._hooks_file,
                self._scripts_dir / "session_start.py",
                self._scripts_dir / "recall.py",
                self._scripts_dir / "retain.py",
            )
            if not path.exists()
        ]
        if missing:
            return self._stamp(RecipeResult.ok(
                RecipeState.ABSENT,
                status="missing " + ", ".join(str(p) for p in missing[:3]),
            ))
        if not _codex_hooks_enabled(self._config_file):
            return self._stamp(RecipeResult.ok(RecipeState.ABSENT, status="codex_hooks disabled"))
        try:
            hooks = json.loads(self._hooks_file.read_text(encoding="utf-8"))
            user_config = json.loads(self._user_config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return self._stamp(RecipeResult.fail(f"Codex Hindsight config unreadable: {exc}"))

        commands = []
        for event in ("SessionStart", "UserPromptSubmit", "Stop"):
            entries = hooks.get("hooks", {}).get(event, [])
            for entry in entries:
                for hook in entry.get("hooks", []):
                    commands.append(str(hook.get("command", "")))
        expected = [
            self._expected_hook_command("session_start.py"),
            self._expected_hook_command("recall.py"),
            self._expected_hook_command("retain.py"),
        ]
        if any(cmd not in commands for cmd in expected):
            return self._stamp(RecipeResult.ok(RecipeState.ABSENT, status="hook commands absent or stale"))
        if user_config.get("hindsightApiUrl") != self._backend.base_url:
            return self._stamp(RecipeResult.ok(RecipeState.ABSENT, status="hindsightApiUrl stale"))
        if self._backend.bank_id and user_config.get("bankId") != self._backend.bank_id:
            return self._stamp(RecipeResult.ok(RecipeState.ABSENT, status="bankId stale"))
        return self._stamp(RecipeResult.ok(
            RecipeState.VERIFIED,
            status="Codex hooks configured",
            artifacts=self._artifacts(),
        ))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        try:
            for rel in _SCRIPT_FILES:
                _download(f"{_RAW_BASE}/{rel}", self._scripts_dir / rel.removeprefix("scripts/"))
            settings = self._install_dir / "settings.json"
            if not settings.exists():
                _download(f"{_RAW_BASE}/settings.json", settings)
        except Exception as exc:  # noqa: BLE001 - installer failure is user-facing
            return self._stamp(RecipeResult.fail(f"Codex Hindsight download failed: {exc}"))
        return self._stamp(RecipeResult.ok(
            RecipeState.INSTALLING,
            status="Codex hook scripts installed",
            artifacts=[str(self._scripts_dir)],
        ))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        from audiagentic.foundation.steps import WriteFileStep

        config: dict[str, Any] = {
            "hindsightApiUrl": self._backend.base_url,
            "bankId": self._backend.bank_id or "codex",
        }
        if self._backend.api_key:
            config["hindsightApiToken"] = self._backend.api_key
        user_step = WriteFileStep(
            id="codex-user-config-write",
            path=str(self._user_config),
            content=json.dumps(config, indent=2) + "\n",
            create_parents=True,
            recipe_id=f"hindsight-{self.provider_id}",
        )
        user_step.run(context)

        hooks = {
            "hooks": {
                "SessionStart": [{"hooks": [{"type": "command", "command": self._expected_hook_command("session_start.py"), "timeout": 5}]}],
                "UserPromptSubmit": [{"hooks": [{"type": "command", "command": self._expected_hook_command("recall.py"), "timeout": 12}]}],
                "Stop": [{"hooks": [{"type": "command", "command": self._expected_hook_command("retain.py"), "timeout": 30}]}],
            }
        }
        hooks_step = WriteFileStep(
            id="codex-hooks-write",
            path=str(self._hooks_file),
            content=json.dumps(hooks, indent=2) + "\n",
            create_parents=True,
            recipe_id=f"hindsight-{self.provider_id}",
        )
        hooks_step.run(context)
        _enable_codex_hooks(self._config_file)
        return self._stamp(RecipeResult.ok(
            RecipeState.CONFIGURING,
            status="Codex hooks configured",
            artifacts=[str(self._user_config), str(self._hooks_file), str(self._config_file)],
        ))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.probe(context)

    # RS18/RS06: intentional one-off — batch removal of downloaded scripts directory
    # plus config files; rmtree + multi-file unlink pattern not expressible via
    # ArtifactRegistry.prune() without per-install registration overhead.
    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        for path in (self._hooks_file, self._user_config):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                return self._stamp(RecipeResult.fail(f"Codex Hindsight uninstall failed: {exc}"))
        try:
            shutil.rmtree(self._scripts_dir)
        except FileNotFoundError:
            pass
        except OSError as exc:
            return self._stamp(RecipeResult.fail(f"Codex Hindsight uninstall failed: {exc}"))
        return self._stamp(RecipeResult.ok(RecipeState.ABSENT, status="Codex hooks removed"))

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.uninstall(context)

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(RecipeResult.ok(
            RecipeState.ABSENT,
            status="would install Codex hook scripts and write hooks.json",
        ))
