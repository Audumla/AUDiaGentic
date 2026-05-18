"""AUDiaGentic provisioning MCP server.

Exposes harness status and configuration for introspection.
Read-only; no mutations.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised by missing optional dep only
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Data collection helpers
# ---------------------------------------------------------------------------

def _get_versions() -> dict[str, Any]:
    """Collect version info for all components."""
    versions: dict[str, Any] = {}

    # Agent version
    try:
        from audiagentic.provisioning.harness.pi.install.constants import AGENT_VERSION, AGENT_MCP_ADAPTER_VERSION
        versions["audiagentic"] = AGENT_VERSION
        versions["mcp_adapter"] = AGENT_MCP_ADAPTER_VERSION
    except Exception:
        pass

    # Llama-server version
    try:
        from audiagentic.provisioning.harness.pi.runner.smoke import query_server_version
        from audiagentic.provisioning.home import global_harness_runtime

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
        from audiagentic.provisioning.harness.pi.runner.models import load_model_profile
        from audiagentic.provisioning.harness.pi.runner.smoke import query_server_version
        from audiagentic.provisioning.home import global_harness_runtime
        from audiagentic.provisioning.config_loader import load_layered_config

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
                from audiagentic.provisioning.harness.pi.install.constants import _HARNESS_CONFIG
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
        from audiagentic.provisioning.home import global_harness_runtime
        from audiagentic.provisioning.harness.pi.install.constants import _HARNESS_CONFIG

        harness = global_harness_runtime()

        # Load layered config (source template → installed overrides → project overrides)
        from audiagentic.provisioning.config_loader import load_layered_config
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
        instructions=(
            "AUDiaGentic session server. "
            "Read-only; exposes harness_info and harness_config."
        ),
    )

    @mcp.tool(description="Show the current AUDiaGentic harness status: versions, model, endpoint, auto-update, and environment info.")
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

    @mcp.tool(description="Show the current AUDiaGentic harness configuration: ag.yaml settings and models.json.")
    def config() -> dict[str, Any]:
        return _get_config_info()

    @mcp.tool(description="Enable or disable auto-update checks at launch.")
    def set_auto_update(enabled: bool) -> dict[str, Any]:
        import os
        env_var = "AUDIAGENTIC_AUTO_UPDATE_ENABLED"
        os.environ[env_var] = str(enabled).lower()
        return {"ok": True, "auto_update_enabled": enabled, "env": env_var}

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
