"""Provider-owned static native-registration facts; never resolve adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.paths.names import get_package_providers_config_dir

from .descriptors.spec import iter_descriptor_files


@dataclass(frozen=True)
class HarnessMcpTarget:
    provider_id: str
    display_name: str
    description: str
    supported: bool
    transports: tuple[str, ...]
    refresh_mode: str
    project_scoped: bool
    user_scoped: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return dict(vars(self))


def list_targets() -> tuple[HarnessMcpTarget, ...]:
    result = []
    for path in iter_descriptor_files(get_package_providers_config_dir()):
        data = load_yaml_file(path)
        mechanism = data.get("capabilities", {}).get("mcp", {}).get("mechanism", {})
        target = mechanism.get("config_path", "")
        # Callable/global paths cannot claim project-native support from static facts.
        scoped = bool(
            target
            and ":" not in target
            and not Path(target).is_absolute()
            and not target.startswith("~")
            and ".." not in Path(target).parts
        )
        scoped = mechanism.get("project_scoped", scoped)
        result.append(
            HarnessMcpTarget(
                data["provider_id"],
                data.get("display_name", data["provider_id"]),
                data.get("description", ""),
                bool(mechanism),
                tuple(mechanism.get("transports", ())),
                mechanism.get("refresh_mode", "none"),
                scoped,
                bool(mechanism.get("user_scope")),
            )
        )
    return tuple(result)
