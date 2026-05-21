"""AUDiaGentic provisioning MCP server.

Exposes harness status and configuration plus lightweight session-scoped
mutations such as CLI visibility toggles.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised by missing optional dep only
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration

register_all_components()


# ---------------------------------------------------------------------------
# Data collection helpers
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    repo_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if repo_root:
        return Path(repo_root)
    raise RuntimeError("AUDIAGENTIC_REPO_ROOT not set for session server")


def _config_path(scope: str, project_root: Path) -> Path:
    if scope == "project":
        return project_root / ".audiagentic" / "config" / "harness" / "ag.yaml"
    if scope == "global":
        from audiagentic.runtime.home import audiagentic_home

        return audiagentic_home() / "config" / "harness" / "ag.yaml"
    raise ValueError(f"unsupported scope: {scope}")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _save_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _effective_cli_visibility(project_root: Path) -> dict[str, bool]:
    from audiagentic.runtime.config_loader import load_layered_config
    from audiagentic.runtime.harness.pi.install.constants import _HARNESS_CONFIG

    cfg = load_layered_config(
        pkg_default_path=_HARNESS_CONFIG,
        project_root=project_root,
        namespace="harness/ag",
    )
    ui = cfg.get("ui", {}) or {}
    return {
        "show_thinking_blocks": not bool(ui.get("hide_thinking_block", False)),
        "show_tool_blocks": not bool(ui.get("hide_tool_use", False)),
    }


def _set_cli_visibility(
    *,
    project_root: Path,
    show_thinking_blocks: bool | None,
    show_tool_blocks: bool | None,
    scope: str,
) -> dict[str, Any]:
    if show_thinking_blocks is None and show_tool_blocks is None:
        raise ValueError("at least one visibility toggle must be provided")

    config_path = _config_path(scope, project_root)
    current = _load_yaml(config_path)
    ui = current.get("ui")
    if not isinstance(ui, dict):
        ui = {}
        current["ui"] = ui

    updates: dict[str, bool] = {}
    if show_thinking_blocks is not None:
        ui["hide_thinking_block"] = not show_thinking_blocks
        updates["show_thinking_blocks"] = show_thinking_blocks
    if show_tool_blocks is not None:
        ui["hide_tool_use"] = not show_tool_blocks
        updates["show_tool_blocks"] = show_tool_blocks

    _save_yaml(config_path, current)

    from audiagentic.runtime.harness.pi.install import (
        refresh_materialized_agent_config,
        request_runtime_reload,
    )
    from audiagentic.runtime.home import global_harness_runtime

    refresh_materialized_agent_config(global_harness_runtime(), project_root=project_root)
    request_runtime_reload(project_root, reason="session-ui-visibility-updated")

    return {
        "ok": True,
        "scope": scope,
        "config_path": str(config_path),
        "updated": updates,
        "effective": _effective_cli_visibility(project_root),
    }


def _server_decl():
    return get_mcp_server_declaration("session", "audiagentic-session")


def _server_instructions() -> str:
    decl = _server_decl()
    return (
        decl.instructions
        if decl and decl.instructions
        else "AUDiaGentic session server. Exposes harness info/config plus CLI visibility controls."
    )


def _tool_description(name: str, fallback: str) -> str:
    decl = _server_decl()
    if decl and name in decl.tool_descriptions:
        return decl.tool_descriptions[name]
    return fallback


def _get_versions() -> dict[str, Any]:
    """Collect version info for all components."""
    versions: dict[str, Any] = {}

    # Agent version
    try:
        from audiagentic.runtime.harness.pi.install.constants import (
            AGENT_MCP_ADAPTER_VERSION,
            AGENT_VERSION,
        )
        versions["audiagentic"] = AGENT_VERSION
        versions["mcp_adapter"] = AGENT_MCP_ADAPTER_VERSION
    except Exception:
        pass

    # Llama-server version
    try:
        from audiagentic.runtime.harness.pi.runner.smoke import query_server_version
        from audiagentic.runtime.home import global_harness_runtime

        harness = global_harness_runtime()
        if harness and (harness / "rig" / "bin").exists():
            server_ver = query_server_version(harness / "rig" / "bin")
            if server_ver:
                versions["llama_server"] = server_ver
    except Exception:
        pass

    return versions


def _get_model_info() -> dict[str, Any]:
    """Collect current model and rig info."""
    info: dict[str, Any] = {}

    try:
        from audiagentic.runtime.config_loader import load_layered_config
        from audiagentic.runtime.harness.pi.runner.models import load_model_profile
        from audiagentic.runtime.harness.pi.runner.smoke import query_server_version
        from audiagentic.runtime.home import global_harness_runtime

        # Get configured model
        requested = os.environ.get("AUDIAGENTIC_AG_MODEL")
        if not requested:
            harness = global_harness_runtime()
            if harness:
                try:
                    cfg = load_layered_config(
                        pkg_default_path=harness / "config" / "provisioning" / "harness" / "ag.yaml",
                        project_root=None,
                        namespace="harness/ag",
                    )
                    requested = cfg.get("model")
                except SystemExit:
                    pass

        if not requested:
            # Fallback: try source tree config
            try:
                from audiagentic.runtime.harness.pi.install.constants import _HARNESS_CONFIG
                cfg = load_layered_config(
                    pkg_default_path=_HARNESS_CONFIG,
                    project_root=None,
                    namespace="harness/ag",
                )
                requested = cfg.get("model")
            except SystemExit:
                pass

        if requested:
            info["configured_model"] = requested
            profile_name, profile = load_model_profile(None, requested)
            info["profile_name"] = profile_name
            info["model_file"] = profile.get("model_file")

            # Server version from installed harness
            harness = global_harness_runtime()
            if harness and (harness / "rig" / "bin").exists():
                server_ver = query_server_version(harness / "rig" / "bin")
                if server_ver:
                    info["server_version"] = server_ver
    except BaseException:
        pass

    return info


def _get_config_info() -> dict[str, Any]:
    """Load and return the current harness configuration."""
    config: dict[str, Any] = {}

    try:
        from audiagentic.runtime.harness.pi.install.constants import _HARNESS_CONFIG
        from audiagentic.runtime.home import global_harness_runtime

        harness = global_harness_runtime()

        # Load layered config (source template → installed overrides → project overrides)
        from audiagentic.runtime.config_loader import load_layered_config
        harness_config = load_layered_config(
            pkg_default_path=_HARNESS_CONFIG,
            project_root=None,
            namespace="harness/ag",
        )
        config["config"] = harness_config
        config["config_path"] = str(_HARNESS_CONFIG)

        if harness:
            models_path = harness / "agent" / "models.json"
            if models_path.exists():
                config["models_path"] = str(models_path)
                config["models"] = json.loads(models_path.read_text(encoding="utf-8"))
            else:
                config["models_path"] = str(models_path)
                config["models"] = {"error": "file not found"}
    except Exception as exc:
        config["error"] = str(exc)

    return config


def _get_endpoint_info() -> dict[str, Any]:
    """Collect endpoint and rig status."""
    info: dict[str, Any] = {}

    base_url = os.environ.get("AUDIAGENTIC_AG_BASE_URL")
    if base_url:
        info["base_url"] = base_url
        info["rig_type"] = os.environ.get("AUDIAGENTIC_RIG_TYPE", "unknown")
        info["rig_profile"] = os.environ.get("AUDIAGENTIC_RIG_PROFILE")

        # Check if endpoint is reachable
        try:
            import urllib.request
            with urllib.request.urlopen(f"{base_url}/models", timeout=5) as resp:
                info["endpoint_reachable"] = resp.status == 200
        except Exception:
            info["endpoint_reachable"] = False
    else:
        info["base_url"] = None
        info["endpoint_reachable"] = False

    return info


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

def build_server() -> FastMCP:
    mcp = FastMCP(
        "audiagentic-session",
        instructions=_server_instructions(),
    )

    @mcp.tool(description=_tool_description("status", "Show the current AUDiaGentic harness status: versions, model, endpoint, auto-update, and environment info."))
    def status() -> dict[str, Any]:
        auto_update: dict[str, Any] = {}
        try:
            from audiagentic.runtime.update.checker import check_update, current_version
            auto_update["installed_version"] = current_version()
            update = check_update(force=True)
            if update:
                auto_update["latest_version"] = update["latest"]
                auto_update["available"] = True
            else:
                auto_update["latest_version"] = auto_update["installed_version"]
                auto_update["available"] = False
            auto_update["enabled"] = os.environ.get("AUDIAGENTIC_AUTO_UPDATE_ENABLED", "true").lower() == "true"
        except Exception as exc:
            auto_update["error"] = str(exc)

        return {
            "versions": _get_versions(),
            "model": _get_model_info(),
            "endpoint": _get_endpoint_info(),
            "auto_update": auto_update,
            "environment": {
                "repo_root": os.environ.get("AUDIAGENTIC_REPO_ROOT"),
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "cwd": str(Path.cwd()),
            },
        }

    @mcp.tool(description=_tool_description("config", "Show the current AUDiaGentic harness configuration: ag.yaml settings and models.json."))
    def config() -> dict[str, Any]:
        return _get_config_info()

    @mcp.tool(description=_tool_description("set_auto_update", "Enable or disable auto-update checks at launch."))
    def set_auto_update(enabled: bool) -> dict[str, Any]:
        import os
        env_var = "AUDIAGENTIC_AUTO_UPDATE_ENABLED"
        os.environ[env_var] = str(enabled).lower()
        return {"ok": True, "auto_update_enabled": enabled, "env": env_var}

    @mcp.tool(description=_tool_description("cli_visibility", "Show current CLI visibility settings for thinking blocks and tool or MCP blocks."))
    def cli_visibility() -> dict[str, Any]:
        return _effective_cli_visibility(_project_root())

    @mcp.tool(description=_tool_description("set_cli_visibility", "Set CLI visibility for thinking blocks and tool or MCP blocks, then request an in-session reload."))
    def set_cli_visibility(
        show_thinking_blocks: bool | None = None,
        show_tool_blocks: bool | None = None,
        scope: str = "project",
    ) -> dict[str, Any]:
        if scope not in {"project", "global"}:
            return {"ok": False, "error": f"unsupported scope: {scope}"}
        try:
            return _set_cli_visibility(
                project_root=_project_root(),
                show_thinking_blocks=show_thinking_blocks,
                show_tool_blocks=show_tool_blocks,
                scope=scope,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @mcp.tool(description=_tool_description("refresh_harness_config", "Regenerate mcp.json and SYSTEM.md from current component state, then request in-session reload."))
    def refresh_harness_config() -> dict[str, Any]:
        from audiagentic.runtime.harness.pi.install import refresh_harness_config_if_installed
        refreshed = refresh_harness_config_if_installed(_project_root(), reason="mcp-refresh-tool")
        return {"ok": refreshed, "refreshed": refreshed}

    return mcp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readonly", action="store_true", help="Read-only mode (no-op, server is always read-only)")
    parser.add_argument("--smoke-only", action="store_true", help="Smoking mode (no-op)")
    args = parser.parse_args()

    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
