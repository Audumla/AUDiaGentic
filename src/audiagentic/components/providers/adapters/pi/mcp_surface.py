"""Pi's implementation of the MCP launch-surface family.

Encapsulates everything pi-specific: applying the system-adapter patch that
makes ``--mcp-config`` exclusive, loading the adapter extension, and building
the resulting CLI args. Nothing outside this module needs to know pi requires
a patch at all — callers go through ``providers_api.prepare_provider_mcp_surface``.
"""
from __future__ import annotations

import logging
from pathlib import Path

from audiagentic.components.providers.contracts.mcp_launch_surface import (
    McpLaunchSurfaceRequest,
    McpLaunchSurfaceResult,
)

logger = logging.getLogger(__name__)


def _materialize_launch_config(request: McpLaunchSurfaceRequest) -> Path | None:
    """Write the immutable request-owned Pi MCP document."""
    if request.runtime_root is None:
        return None
    from audiagentic.foundation.io import atomic_write_json

    target = Path(request.runtime_root).resolve() / "pi" / "mcp" / "launch.json"
    document = {
        "settings": {
            "toolPrefix": "mcp",
            "idleTimeout": 10,
            "directTools": True,
        },
        "mcpServers": {
            entry.name: {
                "command": entry.command,
                "args": list(entry.args),
                "lifecycle": "lazy",
                **({"env": dict(entry.env)} if entry.env else {}),
            }
            for entry in request.entries
        },
    }
    atomic_write_json(target, document, indent=2, sort_keys=False)
    return target


def prepare_mcp_surface(request: McpLaunchSurfaceRequest) -> McpLaunchSurfaceResult:
    import shutil

    from audiagentic.components.providers.adapters.pi.system import (
        resolve_system_pi_mcp_adapter,
    )
    from audiagentic.components.providers.services.host.system_probe import (
        resolve_system_package_root,
    )

    config_path = _materialize_launch_config(request)
    if config_path is None:
        return McpLaunchSurfaceResult(
            ok=False,
            supported=True,
            applied_isolation="unsupported",
            mechanism="pi-request-runtime-required",
        )
    adapter = resolve_system_pi_mcp_adapter()
    has_adapter = adapter is not None

    # Isolation includes extension discovery: a user/global copy of the MCP
    # adapter would otherwise be auto-loaded alongside this explicit one and
    # Pi aborts on duplicate tool/flag registrations before any call returns.
    args: list[str] = ["--no-extensions"]
    if has_adapter:
        args.extend(["--extension", str(adapter)])
    args.extend(["--mcp-config", str(config_path)])

    if not has_adapter:
        return McpLaunchSurfaceResult(
            ok=True,
            supported=True,
            applied_isolation="additive",
            mechanism="additive-fallback (adapter not found)",
            extra_args=tuple(args),
        )

    from audiagentic.components.providers.adapters.pi.mcp_exclusive_patch import (
        apply_mcp_exclusive_patch,
    )

    cli = shutil.which("pi")
    system_root = resolve_system_package_root(cli) if cli else None
    patched = system_root is not None and apply_mcp_exclusive_patch(system_root)
    if patched:
        args.append("--mcp-exclusive")
        return McpLaunchSurfaceResult(
            ok=True,
            supported=True,
            applied_isolation="exact",
            mechanism="pi-mcp-exclusive-patch",
            extra_args=tuple(args),
        )

    logger.warning(
        "pi mcp-exclusive patch could not be applied; launching with additive "
        "MCP discovery instead of an exclusive AUDiaGentic-only surface"
    )
    return McpLaunchSurfaceResult(
        ok=True,
        supported=True,
        applied_isolation="additive",
        mechanism="additive-fallback (patch anchor not found)",
        extra_args=tuple(args),
    )


__all__ = ["prepare_mcp_surface"]
