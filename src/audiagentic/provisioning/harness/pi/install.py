from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _print(msg: str) -> None:
    print(msg, flush=True)

# Pinned Pi version. Update here and re-run `audiagentic install` to upgrade.
AGENT_VERSION = "0.75.1"
AGENT_MCP_ADAPTER_VERSION = "latest"

_AGENT_DIR = Path(__file__).parent
_TEMPLATES_DIR = _AGENT_DIR / "templates" / "home" / "agent"
_PKG_ROOT = _AGENT_DIR.parents[2]         # .../audiagentic/
_SRC_DIR = _AGENT_DIR.parents[3]          # src/
_REPO_ROOT = _AGENT_DIR.parents[4]        # repo root (dev layout)
_MODELS_JSON = _PKG_ROOT / "provisioning" / "rig" / "embedded" / "models.json"
_HARNESS_CONFIG = _PKG_ROOT / "config" / "provisioning" / "harness" / "ag.yaml"

DEFAULT_PROVIDER = "audiagentic"
DEFAULT_API_KEY = "dummy"
DEFAULT_RIG_PORT = 42001


def _npm() -> str:
    resolved = shutil.which("npm")
    if resolved is None:
        raise SystemExit("npm is required to install the AudiaGentic agent.")
    return resolved


def _load_config(project_root: Path | None = None) -> dict:
    from audiagentic.provisioning.config_loader import load_layered_config
    return load_layered_config(
        pkg_default_path=_HARNESS_CONFIG,
        project_root=project_root,
        namespace="harness/ag",
    )


def _audiagentic_pkg_dir(npm_dir: Path) -> Path:
    return npm_dir / "node_modules" / "@earendil-works" / "pi-coding-agent"


# ---------------------------------------------------------------------------
# Lockdown patches
# ---------------------------------------------------------------------------

def _patch_slash_commands(npm_dir: Path, blocked: list[str]) -> None:
    target = _audiagentic_pkg_dir(npm_dir) / "dist" / "core" / "slash-commands.js"
    if not target.exists():
        raise SystemExit(f"AudiaGentic agent install incomplete — not found: {target}")
    source = target.read_text(encoding="utf-8")
    for cmd in blocked:
        source = re.sub(
            rf'[ \t]*\{{[^}}]*\bname:\s*"{re.escape(cmd)}"[^}}]*\}},?\n',
            "",
            source,
        )
    target.write_text(source, encoding="utf-8")


def _patch_interactive_mode(npm_dir: Path, blocked: list[str]) -> None:
    target = (
        _audiagentic_pkg_dir(npm_dir)
        / "dist" / "modes" / "interactive" / "interactive-mode.js"
    )
    if not target.exists():
        raise SystemExit(f"AudiaGentic agent install incomplete — not found: {target}")
    source = target.read_text(encoding="utf-8")
    for cmd in blocked:
        source = re.sub(
            rf'\s+if \(text === "/{re.escape(cmd)}"[^\n]*\n(?:[^\n]*\n)*?[^\n]*return;\n[^\n]*\}}\n',
            "\n",
            source,
        )
    target.write_text(source, encoding="utf-8")


def _patch_tool_execution(npm_dir: Path) -> None:
    target = (
        _audiagentic_pkg_dir(npm_dir)
        / "dist" / "modes" / "interactive" / "components" / "tool-execution.js"
    )
    if not target.exists():
        raise SystemExit(f"AudiaGentic agent install incomplete — not found: {target}")
    source = target.read_text(encoding="utf-8")
    ctor_marker = "this.toolName = toolName;"
    ctor_injection = "if (!toolDefinition) { this.hideComponent = true; }"
    if ctor_injection not in source:
        source = source.replace(ctor_marker, f"{ctor_marker}\n        {ctor_injection}", 1)
    upd_marker = "    updateDisplay() {\n        const bgFn = this.isPartial"
    upd_injection = "    updateDisplay() {\n        if (!this.toolDefinition && !this.builtInToolDefinition) { return; }\n        const bgFn = this.isPartial"
    if upd_injection not in source:
        source = source.replace(upd_marker, upd_injection, 1)
    target.write_text(source, encoding="utf-8")


def _patch_update_notification(npm_dir: Path) -> None:
    target = (
        _audiagentic_pkg_dir(npm_dir)
        / "dist" / "modes" / "interactive" / "interactive-mode.js"
    )
    if not target.exists():
        raise SystemExit(f"AudiaGentic agent install incomplete — not found: {target}")
    source = target.read_text(encoding="utf-8")

    # Suppress Pi self-version check — audiagentic controls which Pi version is installed.
    old_version_check = (
        "        // Start version check asynchronously\n"
        "        checkForNewPiVersion(this.version).then((newVersion) => {\n"
        "            if (newVersion) {\n"
        "                this.showNewVersionNotification(newVersion);\n"
        "            }\n"
        "        });"
    )
    new_version_check = "        // Pi version check suppressed by AUDiaGentic harness — use 'audiagentic update' instead."
    if new_version_check not in source and old_version_check in source:
        source = source.replace(old_version_check, new_version_check, 1)

    # Suppress Pi package update check.
    old_pkg_check = (
        "        // Start package update check asynchronously\n"
        "        this.checkForPackageUpdates().then((updates) => {\n"
        "            if (updates.length > 0) {\n"
        "                this.showPackageUpdateNotification(updates);\n"
        "            }\n"
        "        });"
    )
    new_pkg_check = "        // Package update notifications suppressed by AUDiaGentic harness."
    if new_pkg_check not in source and old_pkg_check in source:
        source = source.replace(old_pkg_check, new_pkg_check, 1)

    target.write_text(source, encoding="utf-8")


def _patch_mcp_oauth_suppress(npm_dir: Path) -> None:
    """Suppress the MCP OAuth callback server startup entirely.

    All our MCP servers are stdio-based so the OAuth callback server (which is
    only needed for HTTP MCP servers) is never used.  On Windows, port 19876 can
    fall in an excluded/reserved range and the bind fails with EACCES regardless
    of address family, producing noisy startup errors.  We make initializeOAuth
    a no-op to avoid this entirely.
    """
    target = npm_dir / "node_modules" / "pi-mcp-adapter" / "mcp-auth-flow.ts"
    if not target.exists():
        return
    source = target.read_text(encoding="utf-8")
    old = (
        "export async function initializeOAuth(): Promise<void> {\n"
        "  await ensureCallbackServer()\n"
        "}"
    )
    new = (
        "export async function initializeOAuth(): Promise<void> {\n"
        "  // Suppressed by AUDiaGentic harness — stdio MCP servers do not need OAuth.\n"
        "}"
    )
    if new not in source and old in source:
        source = source.replace(old, new)
        target.write_text(source, encoding="utf-8")


def _apply_lockdown_patches(npm_dir: Path, project_root: Path | None = None) -> None:
    cfg = _load_config(project_root=project_root)
    blocked = cfg.get("lockdown", {}).get("block_builtin_commands", [])
    if blocked:
        _patch_slash_commands(npm_dir, blocked)
        _patch_interactive_mode(npm_dir, blocked)
        _print(f"Patched AudiaGentic agent: blocked commands {blocked}")
    if cfg.get("ui", {}).get("hide_tool_use"):
        _patch_tool_execution(npm_dir)
        _print("Patched AudiaGentic agent: MCP tool call blocks hidden")
    _patch_update_notification(npm_dir)
    _print("Patched AudiaGentic agent: update notifications suppressed")
    _patch_mcp_oauth_suppress(npm_dir)
    _print("Patched MCP adapter: OAuth callback server suppressed (stdio servers only)")


# ---------------------------------------------------------------------------
# Agent config builders — produce plain dicts, written once at install time.
# AUDIAGENTIC_REPO_ROOT is intentionally absent from mcp.json: it is set in
# Pi's environment by the harness at launch and inherited by MCP subprocesses.
# ---------------------------------------------------------------------------

def _build_models_config(harness_cfg: dict, model_name: str, model_profile: dict) -> dict:
    ag = model_profile.get("ag", {}) if isinstance(model_profile, dict) else {}
    compat: dict = ag.get("compat", {
        "supportsDeveloperRole": False,
        "supportsReasoningEffort": False,
    })
    rig_port = int(harness_cfg.get("rig", {}).get("port", DEFAULT_RIG_PORT))
    endpoint = f"http://127.0.0.1:{rig_port}/v1"
    api_key = DEFAULT_API_KEY
    return {
        "providers": {
            DEFAULT_PROVIDER: {
                "baseUrl": endpoint,
                "api": "openai-completions",
                "apiKey": api_key,
                "compat": compat,
                "models": [
                    {
                        "id": model_name,
                        "name": "AUDiaGentic local planner",
                        "reasoning": bool(ag.get("reasoning", False)),
                        "input": ["text"],
                        "contextWindow": int(ag.get("context_window", 262144)),
                        "maxTokens": int(ag.get("max_tokens", 4096)),
                        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    }
                ],
            }
        }
    }


def _build_mcp_config(harness_cfg: dict) -> dict:
    if not harness_cfg.get("mcp", {}).get("enabled", True):
        return {"settings": {"toolPrefix": "mcp", "idleTimeout": 10, "directTools": False}, "mcpServers": {}}

    extra_args: list[str] = harness_cfg.get("mcp", {}).get("extra_server_args", [])
    src_dir = str(_SRC_DIR).replace("\\", "/")
    python = sys.executable.replace("\\", "/")

    def _server(
        module: str,
        base_args: list[str] = [],
        direct_tools: list[str] | bool = [],
    ) -> dict:
        # AUDIAGENTIC_REPO_ROOT is deliberately omitted — inherited from Pi's env at launch.
        s: dict = {
            "command": python,
            "args": ["-m", module] + base_args + extra_args,
            "env": {"PYTHONPATH": src_dir},
            "lifecycle": "lazy",
        }
        if direct_tools is True or direct_tools:
            s["directTools"] = direct_tools
        return s

    return {
        "settings": {"toolPrefix": "mcp", "idleTimeout": 10, "directTools": True},
        "mcpServers": {
            "audiagentic-provisioning": _server(
                "audiagentic.provisioning.mcp.server",
                ["--readonly", "--smoke-only"],
                ["audiagentic_provisioning_audiagentic_smoke_status"],
            ),
            "audiagentic-project": _server("audiagentic.provisioning.mcp.project_server"),
            "audiagentic-planning": _server("audiagentic.provisioning.mcp.planning_server"),
            "audiagentic-providers": _server("audiagentic.provisioning.mcp.providers_server", direct_tools=True),
            "audiagentic-release-please": _server("audiagentic.provisioning.mcp.release_please_server"),
        },
    }


def _build_settings_config(harness_cfg: dict, target: Path) -> dict:
    ui = harness_cfg.get("ui", {})
    theme_name: str = ui.get("theme", "dark")
    theme_colors = ui.get("theme_colors") or {}

    if theme_colors:
        base_theme_dir = (
            target / "cli" / "node_modules"
            / "@earendil-works" / "pi-coding-agent"
            / "dist" / "modes" / "interactive" / "theme"
        )
        base_path = base_theme_dir / f"{theme_name}.json"
        base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {"vars": {}, "colors": {}, "export": {}}
        base.setdefault("colors", {}).update(theme_colors)
        themes_dir = target / "agent" / "themes"
        themes_dir.mkdir(parents=True, exist_ok=True)
        custom_theme_path = themes_dir / "audiagentic.json"
        custom_theme_path.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
        theme_name = str(custom_theme_path)

    settings: dict = {"theme": theme_name, "extensions": ["extensions/footer.ts"]}
    for key, dest, cast in [
        ("quiet_startup",      "quietStartup",         bool),
        ("collapse_changelog", "collapseChangelog",    bool),
        ("hide_thinking_block","hideThinkingBlock",     bool),
        ("thinking",           "defaultThinkingLevel", str),
        ("editor_padding_x",   "editorPaddingX",       int),
    ]:
        if key in ui:
            settings[dest] = cast(ui[key])
    return settings


def materialize_agent_config(target: Path, harness_cfg: dict) -> None:
    """Write all agent config files from Python dicts. Called at install time.

    Static files (SYSTEM.md, extensions/) are also copied here so the agent
    directory is fully populated after install with no further writes needed at
    launch time.
    """
    agent_dir = target / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Static files — copy once, never touched again.
    for name in ("SYSTEM.md", "APPEND_SYSTEM.md"):
        src = _TEMPLATES_DIR / name
        if src.exists():
            shutil.copy2(src, agent_dir / name)

    ext_src = _TEMPLATES_DIR / "extensions"
    if ext_src.exists():
        shutil.copytree(ext_src, agent_dir / "extensions", dirs_exist_ok=True)

    # Dynamic config — built from dicts, no template substitution.
    model_name: str = harness_cfg.get("model", "qwen3.5-2b-q4_k_s")
    model_profile: dict = {}
    if _MODELS_JSON.exists():
        try:
            data = json.loads(_MODELS_JSON.read_text(encoding="utf-8"))
            model_profile = data.get("models", {}).get(model_name, {})
        except Exception:
            pass

    (agent_dir / "models.json").write_text(
        json.dumps(_build_models_config(harness_cfg, model_name, model_profile), indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_dir / "mcp.json").write_text(
        json.dumps(_build_mcp_config(harness_cfg), indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_dir / "settings.json").write_text(
        json.dumps(_build_settings_config(harness_cfg, target), indent=2) + "\n",
        encoding="utf-8",
    )

    _print(f"Materialized agent config in {agent_dir}")


def install_to(target: Path, project_root: Path | None = None) -> int:
    npm_dir = target / "cli"

    for path in (npm_dir, target / "agent", target / "logs"):
        path.mkdir(parents=True, exist_ok=True)

    # Rig binary and model directories — shared across all projects.
    rig_bin = target / "rig" / "bin"
    for platform_dir in ("windows", "macOS", "linux"):
        (rig_bin / "llama-server" / platform_dir).mkdir(parents=True, exist_ok=True)
    (rig_bin / "models").mkdir(parents=True, exist_ok=True)
    _print(f"Rig binary dir: {rig_bin / 'llama-server'}")
    _print("  Place llama-server binaries in the platform subfolder (windows/macOS/linux).")
    _print(f"Model dir:      {rig_bin / 'models'}")
    _print("  Place .gguf model files here.")

    npm = _npm()

    _print(f"Installing AudiaGentic agent {AGENT_VERSION} into {npm_dir}")
    subprocess.run(
        [npm, "install", "--prefix", str(npm_dir),
         f"@earendil-works/pi-coding-agent@{AGENT_VERSION}"],
        check=True,
    )
    _apply_lockdown_patches(npm_dir, project_root=project_root)

    _print(f"Installing MCP adapter into {npm_dir}")
    subprocess.run(
        [npm, "install", "--prefix", str(npm_dir),
         f"pi-mcp-adapter@{AGENT_MCP_ADAPTER_VERSION}"],
        check=True,
    )

    harness_cfg = _load_config(project_root=project_root)
    materialize_agent_config(target, harness_cfg)
    return 0


def uninstall_from(target: Path) -> int:
    """Remove the Pi harness CLI and generated agent config.

    Rig binaries, models, and logs are left in place because they may be large
    user-managed assets or useful diagnostics.
    """
    for path in (target / "cli", target / "agent"):
        if path.exists():
            shutil.rmtree(path)
    return 0
