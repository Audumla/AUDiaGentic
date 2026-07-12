"""Pi Hindsight extension provisioning."""
from __future__ import annotations

import json
import shutil
import subprocess
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

_PI_SOURCE = "npm:@walodayeet/hindsight-pi"
_PI_PACKAGE = "@walodayeet/hindsight-pi"


def _run_pi(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    exe = shutil.which("pi")
    if exe is None:
        raise RuntimeError("pi is not available on PATH")
    return subprocess.run(  # noqa: S603 - fixed executable and args
        [exe, *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


class PiHindsightRecipe(_RowRecipe):
    """Install and configure the community Hindsight extension for pi."""

    recipe_kind = ProviderRecipeKind.HOOKS

    def __init__(self, row: HindsightRecipeRow, backend: HindsightBackendConfig) -> None:
        super().__init__(row)
        self._backend = backend
        self._config_path = Path.home() / ".hindsight" / "config.json"

    def _artifacts(self) -> list[str]:
        return [
            _PI_SOURCE,
            str(self._config_path),
        ]

    def _pi_list(self) -> str:
        proc = _run_pi(["list"], timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(proc.stdout.strip() or "pi list failed")
        return proc.stdout

    def _extension_installed(self) -> bool:
        try:
            output = self._pi_list()
        except Exception:
            return False
        return _PI_SOURCE in output or _PI_PACKAGE in output

    def _config_valid(self) -> bool:
        data = _load_json(self._config_path)
        host = data.get("host")
        pi = host.get("pi") if isinstance(host, dict) else None
        return (
            data.get("baseUrl") == self._backend.base_url
            and data.get("bankId") == (self._backend.bank_id or "audiagentic")
            and isinstance(pi, dict)
            and pi.get("enabled") is True
        )

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if not self._extension_installed():
            return self._stamp(RecipeResult.ok(RecipeState.ABSENT, status="pi extension absent"))
        if not self._config_valid():
            return self._stamp(RecipeResult.ok(RecipeState.ABSENT, status="pi Hindsight config absent or stale"))
        return self._stamp(RecipeResult.ok(
            RecipeState.VERIFIED,
            status="pi Hindsight extension configured",
            artifacts=self._artifacts(),
        ))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._extension_installed():
            return self._stamp(RecipeResult.ok(
                RecipeState.INSTALLING,
                status="pi extension already installed",
                artifacts=[_PI_SOURCE],
            ))
        try:
            proc = _run_pi(["install", _PI_SOURCE], timeout=300)
        except Exception as exc:  # noqa: BLE001 - user-facing provision error
            return self._stamp(RecipeResult.fail(f"pi extension install failed: {exc}"))
        if proc.returncode != 0:
            return self._stamp(RecipeResult.fail(
                "pi extension install failed: " + (proc.stdout.strip() or f"exit {proc.returncode}")
            ))
        return self._stamp(RecipeResult.ok(
            RecipeState.INSTALLING,
            status="pi extension installed",
            artifacts=[_PI_SOURCE],
        ))

    # RS18/RS06: intentional one-off — config content includes literal brace
    # placeholders (e.g. "{project}") that would be misinterpreted by
    # WriteFileStep's variable substitution; bare write_text is required here.
    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        data = _load_json(self._config_path)
        data["baseUrl"] = self._backend.base_url
        data["bankId"] = self._backend.bank_id or "audiagentic"
        data.setdefault("bankStrategy", "manual")
        host = data.setdefault("host", {})
        if not isinstance(host, dict):
            host = {}
            data["host"] = host
        pi = host.setdefault("pi", {})
        if not isinstance(pi, dict):
            pi = {}
            host["pi"] = pi
        pi.update({
            "enabled": True,
            "recallMode": pi.get("recallMode", "hybrid"),
            "autoRecallTags": pi.get("autoRecallTags", ["{project}"]),
            "autoRecallTagsMatch": pi.get("autoRecallTagsMatch", "any_strict"),
            "observationScopes": pi.get("observationScopes", [["{project}"]]),
        })
        self._config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return self._stamp(RecipeResult.ok(
            RecipeState.CONFIGURING,
            status="pi Hindsight config written",
            artifacts=[str(self._config_path)],
        ))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.probe(context)

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        try:
            proc = _run_pi(["remove", _PI_SOURCE], timeout=180)
        except Exception as exc:  # noqa: BLE001
            return self._stamp(RecipeResult.fail(f"pi extension remove failed: {exc}"))
        if proc.returncode != 0 and "not installed" not in proc.stdout.lower():
            return self._stamp(RecipeResult.fail(
                "pi extension remove failed: " + (proc.stdout.strip() or f"exit {proc.returncode}")
            ))
        return self.prune(context)

    # RS18/RS06: intentional one-off — surgical JSON key removal from a shared config
    # file; not expressible via WriteFileStep because only the "host.pi" key must be
    # removed while preserving other top-level settings.
    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        data = _load_json(self._config_path)
        host = data.get("host")
        if isinstance(host, dict):
            host.pop("pi", None)
        try:
            if data:
                self._config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            return self._stamp(RecipeResult.fail(f"pi Hindsight config prune failed: {exc}"))
        return self._stamp(RecipeResult.ok(RecipeState.ABSENT, status="pi Hindsight config pruned"))

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(RecipeResult.ok(
            RecipeState.ABSENT,
            status=f"would run pi install {_PI_SOURCE} and write {self._config_path}",
        ))
