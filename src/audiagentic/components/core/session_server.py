"""AUDiaGentic session MCP server.

Exposes harness status and configuration plus lightweight session-scoped
mutations such as CLI visibility toggles.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.server import Context
except ImportError:  # pragma: no cover - exercised by missing optional dep only
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

from audiagentic.foundation.components.ids import COMPONENT_SESSION
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration
from audiagentic.runtime.config import load_layered_config, load_yaml_file, save_yaml_file

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


def _save_yaml(path: Path, payload: dict[str, Any]) -> None:
    save_yaml_file(path, payload, sort_keys=False)


def _effective_cli_visibility(project_root: Path) -> dict[str, bool]:
    from audiagentic.runtime.harness import default_config_path

    cfg = load_layered_config(
        pkg_default_path=default_config_path(),
        project_root=project_root,
        namespace="harness/ag",
    )
    ui = cfg.get("ui", {}) or {}
    return {
        "show_thinking_blocks": not bool(ui.get("hide_thinking_block", False)),
        "show_tool_blocks": not bool(ui.get("hide_tool_use", False)),
    }


def _active_embedded_rig_profile() -> str | None:
    if os.environ.get("AUDIAGENTIC_RIG_TYPE") != "embedded":
        return None
    profile = os.environ.get("AUDIAGENTIC_RIG_PROFILE")
    if isinstance(profile, str) and profile.strip():
        return profile.strip()
    return None


def _active_embedded_rig_port() -> int:
    endpoint = os.environ.get("AUDIAGENTIC_AG_BASE_URL")
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.port is not None:
            return int(parsed.port)
    return 42001


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
    current = load_yaml_file(config_path)
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

    from audiagentic.runtime.harness import (
        build_runtime_sync,
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
        "sync": build_runtime_sync(reason="session-ui-visibility-updated"),
    }


def _server_decl():
    return get_mcp_server_declaration(COMPONENT_SESSION, "audiagentic-session")


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
        from audiagentic.runtime.harness import version_info
        vi = version_info()
        versions["audiagentic"] = vi["agent"]
        versions["mcp_adapter"] = vi["mcp_adapter"]
    except Exception as exc:
        versions["audiagentic_error"] = str(exc)

    # Llama-server version
    try:
        from audiagentic.runtime.harness import query_rig_server_version
        from audiagentic.runtime.home import global_harness_runtime

        harness = global_harness_runtime()
        if harness and (harness / "rig" / "bin").exists():
            server_ver = query_rig_server_version(harness / "rig" / "bin")
            if server_ver:
                versions["llama_server"] = server_ver
    except Exception as exc:
        versions["llama_server_error"] = str(exc)

    return versions


def _get_model_info() -> dict[str, Any]:
    """Collect current model and rig info."""
    info: dict[str, Any] = {}

    from audiagentic.runtime.harness import (
        default_config_path,
        load_active_profile,
        query_rig_server_version,
    )
    from audiagentic.runtime.home import global_harness_runtime

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
            except SystemExit as exc:
                info["config_error"] = str(exc)

    if not requested:
        try:
            cfg = load_layered_config(
                pkg_default_path=default_config_path(),
                project_root=None,
                namespace="harness/ag",
            )
            requested = cfg.get("model")
        except SystemExit as exc:
            info["config_error"] = str(exc)

    if requested:
        info["configured_model"] = requested
        try:
            profile_name, profile = load_active_profile(None, requested)
            info["profile_name"] = profile_name
            info["model_file"] = profile.get("model_file")
        except Exception as exc:
            info["profile_error"] = str(exc)

        harness = global_harness_runtime()
        if harness and (harness / "rig" / "bin").exists():
            try:
                server_ver = query_rig_server_version(harness / "rig" / "bin")
                if server_ver:
                    info["server_version"] = server_ver
            except Exception as exc:
                info["server_version_error"] = str(exc)

    return info


def _get_config_info() -> dict[str, Any]:
    """Load and return the current harness configuration."""
    config: dict[str, Any] = {}

    try:
        from audiagentic.runtime.harness import default_config_path
        from audiagentic.runtime.home import global_harness_runtime

        harness = global_harness_runtime()
        cfg_path = default_config_path()
        harness_config = load_layered_config(
            pkg_default_path=cfg_path,
            project_root=None,
            namespace="harness/ag",
        )
        config["config"] = harness_config
        config["config_path"] = str(cfg_path)

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

    @mcp.tool(description=_tool_description("config", "Show the current AUDiaGentic harness configuration: ag.yaml settings and generated agent model config."))
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
        from audiagentic.runtime.harness import (
            build_runtime_sync,
            refresh_harness_config_if_installed,
        )
        refreshed = refresh_harness_config_if_installed(_project_root(), reason="mcp-refresh-tool")
        return {
            "ok": refreshed,
            "refreshed": refreshed,
            "sync": build_runtime_sync(reason="mcp-refresh-tool"),
        }

    @mcp.tool(description=_tool_description("update_embedded_rig", "Update the embedded rig's llama-server binary to the latest ggml-org/llama.cpp release."))
    async def update_embedded_rig(ctx: Context) -> dict[str, Any]:
        import contextlib
        import io

        from audiagentic.foundation.mcp.component_server import run_blocking_with_output
        from audiagentic.foundation.output import ComponentOutputEvent
        from audiagentic.foundation.system.process import kill_pid
        from audiagentic.runtime.rig.embedded.binaries import update_binaries as _update
        from audiagentic.runtime.rig.embedded.launch import runtime_bin_dir, start_embedded_rig
        from audiagentic.runtime.rig.registry import (
            _clear_rig_state,
            ensure_rig_state,
            read_rig_state,
            write_rig_state,
        )

        def _work(sink):
            out = io.StringIO()
            try:
                bin_dir = runtime_bin_dir()
                active_profile = _active_embedded_rig_profile()
                active_state = None
                if active_profile:
                    active_state = read_rig_state()
                    if active_state is None:
                        active_state = ensure_rig_state(_active_embedded_rig_port(), model=active_profile)
                if sink:
                    if active_state and active_profile:
                        sink(
                            ComponentOutputEvent(
                                message=(
                                    f"[rig] stopping embedded rig '{active_profile}' on "
                                    f"{active_state.get('endpoint', 'unknown endpoint')}"
                                )
                            )
                        )
                    else:
                        sink(ComponentOutputEvent(message="[rig] updating embedded rig binaries"))

                if active_state and active_profile:
                    kill_pid(int(active_state["pid"]))
                    deadline = time.time() + 15.0
                    while time.time() < deadline:
                        try:
                            os.kill(int(active_state["pid"]), 0)
                        except OSError:
                            break
                        time.sleep(0.25)
                    _clear_rig_state()

                with contextlib.redirect_stdout(out):
                    _update(target_bin_dir=bin_dir)

                restarted: dict[str, Any] | None = None
                if active_state and active_profile:
                    port = int(active_state["port"])
                    if sink:
                        sink(ComponentOutputEvent(message=f"[rig] restarting embedded rig '{active_profile}'"))
                    launch_result = start_embedded_rig(
                        model_profile=active_profile,
                        port=port,
                        health_timeout=90.0,
                        on_progress=(lambda message: sink(ComponentOutputEvent(message=message))) if sink else None,
                    )
                    restarted = {
                        "pid": int(launch_result.pid),
                        "port": int(launch_result.port),
                        "base_url": str(launch_result.base_url),
                    }
                    write_rig_state(
                        int(restarted["pid"]),
                        int(restarted["port"]),
                        str(restarted["base_url"]),
                        active_profile,
                    )
                    if sink:
                        sink(
                            ComponentOutputEvent(
                                message=(
                                    f"[rig] embedded rig '{active_profile}' healthy at "
                                    f"{restarted['base_url']}"
                                )
                            )
                        )
                if sink:
                    sink(ComponentOutputEvent(message=out.getvalue().strip()))
                return {
                    "ok": True,
                    "output": out.getvalue().strip(),
                    "restarted": restarted is not None,
                    "endpoint": restarted["base_url"] if restarted else None,
                    "profile": active_profile,
                }
            except Exception as exc:
                return {"ok": False, "error": str(exc), "output": out.getvalue().strip()}

        result = await run_blocking_with_output(
            ctx=ctx,
            logger="session.update_rig",
            heartbeat_message="[rig] update still running...",
            work=_work,
        )
        return result

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
