"""Typed Hindsight-owned plugin recipe values."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
    provider_id: str
    plugin_id: str | None = None
    settings_path: Path | None = None
    repair_cache_pattern: str = ""
    repair_data_dir: str = ""
    repair_venv_python: str = ""
    repair_server_script: str = ""

    @classmethod
    def from_row(cls, row: HindsightRecipeRow) -> HindsightPluginDefinition:
        return cls(
            provider_id=row.provider_id,
            plugin_id=row.plugin_array_package or None,
            settings_path=Path(row.plugin_url_config_path).expanduser()
            if row.plugin_url_config_path else None,
            repair_cache_pattern=row.plugin_repair_cache_pattern,
            repair_data_dir=row.plugin_repair_data_dir,
            repair_venv_python=row.plugin_repair_venv_python,
            repair_server_script=row.plugin_repair_server_script,
        )

    def to_mapping(self) -> dict[str, str | None]:
        return {
            "provider_id": self.provider_id,
            "plugin_id": self.plugin_id,
            "settings_path": str(self.settings_path) if self.settings_path else None,
            "repair_cache_pattern": self.repair_cache_pattern,
            "repair_data_dir": self.repair_data_dir,
            "repair_venv_python": self.repair_venv_python,
            "repair_server_script": self.repair_server_script,
        }


__all__ = ["HindsightPluginDefinition", "HindsightPluginDesired"]
