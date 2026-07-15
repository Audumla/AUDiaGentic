"""Typed Hindsight-owned declared integration recipes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
from audiagentic.components.memory.hindsight.recipes import _RowRecipe
from audiagentic.components.providers.services.recipes import ProviderRecipeResult, RecipeState
from audiagentic.foundation.steps import ShellStep
from audiagentic.foundation.toolchains.recipe_contract import run_steps


@dataclass(frozen=True)
class IntegrationCommand:
    id: str
    command: tuple[str, ...]
    shell: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any], *, default_id: str) -> IntegrationCommand:
        if value.get("type") != "shell":
            raise ValueError("declared integration supports shell steps only")
        command = value.get("command")
        shell = bool(value.get("shell", False))
        if isinstance(command, str) and command:
            import shlex

            parts = (command,) if shell else tuple(shlex.split(command))
        elif isinstance(command, list) and command:
            parts = tuple(str(part) for part in command)
        else:
            raise ValueError("declared integration command must be a string or non-empty list")
        return cls(id=str(value.get("id") or default_id), command=parts, shell=shell)

    def to_mapping(self) -> dict[str, Any]:
        return {"id": self.id, "command": list(self.command), "shell": self.shell}


@dataclass(frozen=True)
class DeclaredIntegrationDefinition:
    integration_id: str
    provider_id: str
    install: tuple[IntegrationCommand, ...]
    uninstall: tuple[IntegrationCommand, ...]
    status_command: tuple[str, ...] = ()
    verified: bool = True
    source_label: str = ""
    gate_action: str = ""

    @classmethod
    def from_row(cls, row: HindsightRecipeRow) -> DeclaredIntegrationDefinition:
        return cls(
            integration_id=f"hindsight-{row.provider_id}",
            provider_id=row.provider_id,
            install=tuple(
                IntegrationCommand.from_mapping(step, default_id=f"install-{index}")
                for index, step in enumerate(row.install_steps)
            ),
            uninstall=tuple(
                IntegrationCommand.from_mapping(step, default_id=f"uninstall-{index}")
                for index, step in enumerate(row.uninstall_steps)
            ),
            status_command=tuple(row.status_command.split()) if row.status_command else (),
            verified=row.source_status == "verified",
            source_label=row.source_status,
            gate_action=row.notes or row.audia_action,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "integration_id": self.integration_id,
            "provider_id": self.provider_id,
            "install": [step.to_mapping() for step in self.install],
            "uninstall": [step.to_mapping() for step in self.uninstall],
            "status_command": list(self.status_command),
            "verified": self.verified,
            "source_label": self.source_label,
            "gate_action": self.gate_action,
        }


@dataclass(frozen=True)
class HindsightIntegrationDesired:
    endpoint_url: str
    api_token: str | None = None
    bank_id: str | None = None

    @classmethod
    def from_backend(cls, backend: HindsightBackendConfig) -> HindsightIntegrationDesired:
        return cls(
            endpoint_url=backend.base_url,
            api_token=backend.api_key,
            bank_id=backend.bank_id,
        )


def _render(command: tuple[str, ...], desired: HindsightIntegrationDesired) -> tuple[str, ...]:
    values = {
        "URL": desired.endpoint_url,
        "KEY": desired.api_token or "",
        "TOKEN": desired.api_token or "",
        "ID": desired.bank_id or "",
    }
    rendered = tuple(
        next((part.replace(f"{{{key}}}", value) for key, value in values.items() if f"{{{key}}}" in part), part)
        for part in command
    )
    return tuple(part for part in rendered if not part.endswith("="))


class DeclaredHindsightIntegrationRecipe(_RowRecipe):
    """Execute one typed Hindsight integration definition."""

    def __init__(
        self,
        row: HindsightRecipeRow,
        definition: DeclaredIntegrationDefinition,
        desired: HindsightIntegrationDesired,
    ) -> None:
        super().__init__(row)
        self._definition = definition
        self._desired = desired

    def _steps(self, commands: tuple[IntegrationCommand, ...]) -> list[ShellStep]:
        return [
            ShellStep(
                id=step.id,
                command=_render(step.command, self._desired),
                shell=step.shell,
            )
            for step in commands
        ]

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if not self._definition.verified:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status=f"source {self._definition.source_label}; integration blocked",
                action_needed=self._definition.gate_action,
            ))
        command = self._definition.status_command
        if not command:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status="no integration status probe declared",
            ))
        result = ShellStep(id="integration-status", command=_render(command, self._desired)).run(context)
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.VERIFIED if result.status == "ok" else RecipeState.ABSENT,
            status="integration status verified" if result.status == "ok" else "integration status unavailable",
        ))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if not self._definition.verified:
            return self._stamp(ProviderRecipeResult.fail(
                f"integration source {self._definition.source_label}; refusing to execute",
                action_needed=self._definition.gate_action,
            ))
        result = run_steps(
            self._steps(self._definition.install), context,
            ok_state=RecipeState.INSTALLING,
            ok_status="integration installer succeeded",
            fail_prefix="integration installer failed",
        )
        return self._stamp(result)

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.CONFIGURING, status="integration configured by installer",
        ))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if not self._definition.status_command:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.VERIFIED, status="integration installer completed",
            ))
        return self.probe(context)

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if not self._definition.verified:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status="unverified integration was not executed",
                action_needed=self._definition.gate_action,
            ))
        if not self._definition.uninstall:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="no integration uninstaller declared",
            ))
        return self._stamp(run_steps(
            self._steps(self._definition.uninstall), context,
            ok_state=RecipeState.ABSENT,
            ok_status="integration uninstaller succeeded",
            fail_prefix="integration uninstaller failed",
        ))

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="integration owns no direct config fragments",
        ))

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="would run typed integration recipe",
        ))

    def provision_steps(self) -> list[ShellStep]:
        return self._steps(self._definition.install)


def build_declared_integration_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
) -> DeclaredHindsightIntegrationRecipe:
    return DeclaredHindsightIntegrationRecipe(
        row,
        DeclaredIntegrationDefinition.from_row(row),
        HindsightIntegrationDesired.from_backend(backend),
    )


__all__ = [
    "DeclaredHindsightIntegrationRecipe",
    "DeclaredIntegrationDefinition",
    "HindsightIntegrationDesired",
    "IntegrationCommand",
    "build_declared_integration_recipe",
]
