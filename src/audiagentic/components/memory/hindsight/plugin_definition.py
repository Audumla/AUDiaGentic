"""Typed Hindsight-owned plugin recipe values."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.declared_integration import IntegrationCommand
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow


@dataclass(frozen=True)
class HindsightPluginDesired:
    endpoint_url: str
    api_token: str | None = None
    bank_id: str | None = None

    @classmethod
    def from_backend(cls, backend: HindsightBackendConfig) -> HindsightPluginDesired:
        return cls(backend.base_url, backend.api_key, backend.bank_id)

    def options(self) -> dict[str, str]:
        result = {"hindsightApiUrl": self.endpoint_url}
        if self.api_token:
            result["hindsightApiToken"] = self.api_token
        if self.bank_id:
            result["bankId"] = self.bank_id
        return result


@dataclass(frozen=True)
class HindsightPluginDefinition:
    # Identity
    provider_id: str
    plugin_id: str | None = None

    # Provenance (extracted from row at Hindsight boundary)
    display_name: str = ""
    source_url: str = ""
    source_date: str = ""
    audia_action: str = ""
    source_status: str = ""
    notes: str = ""

    # Plugin config paths
    settings_path: Path | None = None

    # Plugin repair metadata (Windows-specific)
    repair_cache_pattern: str = ""
    repair_data_dir: str = ""
    repair_venv_python: str = ""
    repair_server_script: str = ""

    # Typed plugin-array desired package/source data
    plugin_array_package: str | None = None

    # Typed step commands (parsed once at Hindsight boundary)
    install_steps: tuple[IntegrationCommand, ...] = ()
    configure_steps: tuple[IntegrationCommand, ...] = ()
    uninstall_steps: tuple[IntegrationCommand, ...] = ()

    @classmethod
    def from_row(cls, row: HindsightRecipeRow) -> HindsightPluginDefinition:
        return cls(
            provider_id=row.provider_id,
            plugin_id=row.plugin_array_package or None,
            display_name=row.display_name,
            source_url=row.source_url,
            source_date=row.source_date,
            audia_action=row.audia_action,
            source_status=row.source_status,
            notes=row.notes,
            settings_path=Path(row.plugin_url_config_path).expanduser()
            if row.plugin_url_config_path else None,
            repair_cache_pattern=row.plugin_repair_cache_pattern,
            repair_data_dir=row.plugin_repair_data_dir,
            repair_venv_python=row.plugin_repair_venv_python,
            repair_server_script=row.plugin_repair_server_script,
            plugin_array_package=row.plugin_array_package or None,
            install_steps=tuple(
                IntegrationCommand.from_mapping(step, default_id=f"install-{index}")
                for index, step in enumerate(row.install_steps)
            ),
            configure_steps=tuple(
                IntegrationCommand.from_mapping(step, default_id=f"configure-{index}")
                for index, step in enumerate(row.configure_steps)
            ),
            uninstall_steps=tuple(
                IntegrationCommand.from_mapping(step, default_id=f"uninstall-{index}")
                for index, step in enumerate(row.uninstall_steps)
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "plugin_id": self.plugin_id,
            "display_name": self.display_name,
            "source_url": self.source_url,
            "source_date": self.source_date,
            "audia_action": self.audia_action,
            "source_status": self.source_status,
            "notes": self.notes,
            "settings_path": str(self.settings_path) if self.settings_path else None,
            "repair_cache_pattern": self.repair_cache_pattern,
            "repair_data_dir": self.repair_data_dir,
            "repair_venv_python": self.repair_venv_python,
            "repair_server_script": self.repair_server_script,
            "plugin_array_package": self.plugin_array_package,
            "install_steps": [step.to_mapping() for step in self.install_steps],
            "configure_steps": [step.to_mapping() for step in self.configure_steps],
            "uninstall_steps": [step.to_mapping() for step in self.uninstall_steps],
        }


__all__ = ["HindsightPluginDefinition", "HindsightPluginDesired"]
