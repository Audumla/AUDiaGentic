"""Opencode's implementation of the MCP launch-surface family.

Stock opencode reads MCP servers ONLY from its own native config
(``opencode.json``/``.jsonc`` — including the project-scoped
``.opencode/opencode.json``, populated by the pre-existing provider-projection
mechanism for ``propagate: providers`` servers). It does NOT read bare
``.mcp.json`` at all — confirmed empirically (schema mismatch, ``--pure``
rules out a plugin) and confirmed against upstream (reading ``.mcp.json`` was
requested and closed as not planned).

``OPENCODE_CONFIG_CONTENT`` is a real, documented-by-behavior per-process
environment variable, confirmed empirically to be loaded AFTER project config
and merged per-field, per-server (last-wins) — and ``enabled: false`` is
confirmed to genuinely suppress connection (opencode reports the server as
"disabled", never attempts to connect). Building an override that explicitly
disables every server the project's own config discovers, then explicitly
(re)enables the caller-supplied curated set, reliably yields an exclusive
surface with zero file writes and zero risk of colliding with the
provider-projection file.
"""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.contracts.mcp_launch_surface import (
    McpLaunchSurfaceRequest,
    McpLaunchSurfaceResult,
)


def _discover_project_mcp_names(project_root: Path) -> set[str]:
    """Server names opencode's own native config would otherwise expose.

    Reads ``.opencode/opencode.json`` directly — the confirmed real target of
    opencode's provider-projection MCP config, per
    ``get_descriptor("opencode").mcp_config.config_path``.
    """
    path = project_root / ".opencode" / "opencode.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    mcp = data.get("mcp")
    return set(mcp.keys()) if isinstance(mcp, dict) else set()


def prepare_mcp_surface(request: McpLaunchSurfaceRequest) -> McpLaunchSurfaceResult:
    project_root = Path(request.project_root)
    if request.runtime_root is None:
        return McpLaunchSurfaceResult(
            ok=False,
            supported=True,
            applied_isolation="unsupported",
            mechanism="opencode-request-runtime-required",
        )
    isolated_config_home = Path(request.runtime_root).resolve() / "opencode" / "xdg"
    isolated_config_home.mkdir(parents=True, exist_ok=True)
    suppress = _discover_project_mcp_names(project_root) - {e.name for e in request.entries}

    overrides: dict[str, dict] = {name: {"enabled": False} for name in suppress}
    for entry in request.entries:
        overrides[entry.name] = {
            "type": "local",
            "command": [entry.command, *entry.args],
            **({"environment": dict(entry.env)} if entry.env else {}),
            "enabled": True,
        }

    content = json.dumps({"mcp": overrides, "plugin": []})
    return McpLaunchSurfaceResult(
        ok=True,
        supported=True,
        applied_isolation="exact",
        mechanism="opencode-config-content",
        extra_env=(
            ("XDG_CONFIG_HOME", str(isolated_config_home)),
            ("OPENCODE_CONFIG_CONTENT", content),
        ),
    )


__all__ = ["prepare_mcp_surface"]
