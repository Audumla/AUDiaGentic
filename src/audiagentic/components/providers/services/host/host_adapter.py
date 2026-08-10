"""Pluggable, config-driven editor-host adapter (AR09).

Host-specific behavior (workspace detection, extension manifest location,
installed-extension probing) resolves through a HostAdapter built from
config/components/providers/hosts.yaml. Adding a second editor host is a
config drop plus provider ``host_capabilities`` entries — no code change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.paths.names import get_package_config_dir
from audiagentic.foundation.registry_utils import Registry

_HOSTS_CONFIG = get_package_config_dir() / "components" / "providers" / "hosts.yaml"

_EXT_ID_RE = re.compile(r"^([a-zA-Z0-9_-]+.[a-zA-Z0-9_-]+?)(?:-\d+.*)?$")


@dataclass
class HostAdapter:
    """Filesystem seam for one editor host, driven entirely by descriptor data."""

    host_id: str
    workspace_marker: str
    extensions_manifest: str
    extensions_dir: str
    display_name: str = ""
    settings_manifest: str = ""
    _ext_cache: list[str] | None = field(default=None, repr=False)
    _ext_probed: bool = field(default=False, repr=False)

    def detect_workspace(self, project_root: Path) -> bool:
        return (project_root / self.workspace_marker).exists()

    def extensions_manifest_path(self, project_root: Path) -> Path:
        return project_root / self.extensions_manifest

    def settings_manifest_path(self, project_root: Path) -> Path:
        if not self.settings_manifest:
            raise make_error(
                prefix="CFG",
                component="HOST",
                number=2,
                kind="providers",
                message=f"host {self.host_id!r} has no settings-manifest configured",
                details={"host-id": self.host_id},
            )
        return project_root / self.settings_manifest

    def extension_dir(self) -> Path:
        return Path(self.extensions_dir).expanduser()

    def installed_extension_ids(self, *, allow_probe: bool = True) -> list[str] | None:
        """Return installed extension IDs without spawning the host."""
        if self._ext_probed:
            return self._ext_cache
        if not allow_probe:
            return None
        self._ext_probed = True
        ext_dir = self.extension_dir()
        if not ext_dir.exists():
            self._ext_cache = None
            return None
        ids: list[str] = []
        try:
            for path in ext_dir.iterdir():
                if not path.is_dir() or path.name.startswith("."):
                    continue
                match = _EXT_ID_RE.match(path.name)
                if match:
                    ids.append(match.group(1).lower())
        except OSError:
            self._ext_cache = None
            return None
        self._ext_cache = ids
        return self._ext_cache


_registry: Registry[HostAdapter]


def _load_hosts() -> None:
    data = load_yaml_file(_HOSTS_CONFIG)
    for host_id, spec in (data.get("hosts") or {}).items():
        if _registry.get(host_id) is not None:
            continue
        _registry.register(
            host_id,
            HostAdapter(
                host_id=host_id,
                workspace_marker=spec["workspace-marker"],
                extensions_manifest=spec["extensions-manifest"],
                extensions_dir=spec["extensions-dir"],
                display_name=spec.get("display-name", host_id),
                settings_manifest=spec.get("settings-manifest", ""),
            ),
        )


_registry = Registry(loader=_load_hosts)


def register_host_adapter(adapter: HostAdapter) -> None:
    """Register an additional host adapter (tests, plugins)."""
    _registry.register(adapter.host_id, adapter, replace=True)


def get_host_adapter(host_id: str) -> HostAdapter:
    adapter = _registry.get(host_id)
    if adapter is None:
        raise make_error(
            prefix="CFG",
            component="HOST",
            number=1,
            kind="providers",
            message=f"unknown editor host: {host_id!r}",
            details={"host-id": host_id, "known": sorted(_registry.keys())},
        )
    return adapter


def all_host_adapters() -> dict[str, HostAdapter]:
    return _registry.all()
