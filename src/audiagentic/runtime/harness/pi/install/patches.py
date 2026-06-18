from __future__ import annotations

import re
from pathlib import Path

from . import constants as _c
from .patches_mcp_progress import (
    _patch_mcp_direct_tools_progress,
    _patch_mcp_proxy_progress,
)
from .patches_mcp_register import _patch_mcp_direct_tools_live_register


def _patch_slash_commands(npm_dir: Path, blocked: list[str]) -> None:
    target = _c._audiagentic_pkg_dir(npm_dir) / "dist" / "core" / "slash-commands.js"
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
        _c._audiagentic_pkg_dir(npm_dir)
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
        _c._audiagentic_pkg_dir(npm_dir)
        / "dist" / "modes" / "interactive" / "components" / "tool-execution.js"
    )
    if not target.exists():
        raise SystemExit(f"AudiaGentic agent install incomplete — not found: {target}")
    source = target.read_text(encoding="utf-8")

    helper_import = 'import { existsSync, readFileSync } from "fs";'
    if helper_import not in source:
        marker = 'import { convertToPng } from "../../../utils/image-convert.js";'
        if marker in source:
            source = source.replace(
                marker,
                marker + '\n' + helper_import + '\nimport { join } from "path";',
                1,
            )

    helper_fn = (
        "function _audiagenticHideToolUse() {\n"
        "    try {\n"
        "        const agentDir = process.env.PI_CODING_AGENT_DIR;\n"
        "        if (!agentDir) return false;\n"
        '        const settingsPath = join(agentDir, "settings.json");\n'
        "        if (!existsSync(settingsPath)) return false;\n"
        '        const payload = JSON.parse(readFileSync(settingsPath, "utf-8"));\n'
        "        return !!payload.audiagenticHideToolUse;\n"
        "    }\n"
        "    catch {\n"
        "        return false;\n"
        "    }\n"
        "}\n"
    )
    if "function _audiagenticHideToolUse()" not in source:
        marker = 'import { theme } from "../theme/theme.js";'
        if marker in source:
            source = source.replace(marker, marker + "\n" + helper_fn, 1)

    # Constructor: hide audiagentic_ tools.
    ctor_injection = (
        "if (!toolDefinition || (toolName && toolName.startsWith('audiagentic_') && _audiagenticHideToolUse())) "
        "{ this.hideComponent = true; }"
    )
    ctor_marker = "this.toolName = toolName;"
    if ctor_injection not in source:
        source = source.replace(ctor_marker, f"{ctor_marker}\n        {ctor_injection}", 1)

    # updateDisplay(): preserve hideComponent for audiagentic_ tools.
    # The constructor sets hideComponent=true but updateDisplay() resets it to false.
    # Replace the unconditional reset with a conditional that preserves the flag.
    hide_reset = "        this.hideComponent = false;"
    hide_guard = (
        "        if (!(this.toolName && this.toolName.startsWith('audiagentic_') && _audiagenticHideToolUse())) {\n"
        "            this.hideComponent = false;\n"
        "        }"
    )
    if hide_guard not in source and hide_reset in source:
        source = source.replace(hide_reset, hide_guard, 1)
    elif hide_guard in source:
        pass  # already patched
    else:
        # Fallback: inject guard after the early return in updateDisplay.
        early_return = "        if (!this.toolDefinition && !this.builtInToolDefinition) { return; }"
        if early_return in source and hide_guard not in source:
            source = source.replace(
                early_return,
                f"{early_return}\n        if (this.toolName && this.toolName.startsWith('audiagentic_')) {{ this.hideComponent = true; }}",
                1,
            )

    target.write_text(source, encoding="utf-8")


def _patch_update_notification(npm_dir: Path) -> None:
    import re as _re

    target = (
        _c._audiagentic_pkg_dir(npm_dir)
        / "dist" / "modes" / "interactive" / "interactive-mode.js"
    )
    if not target.exists():
        raise SystemExit(f"AudiaGentic agent install incomplete — not found: {target}")
    source = target.read_text(encoding="utf-8")

    # Match the version-check block regardless of the callback variable name.
    new_version_check = "        // Pi version check suppressed by AUDiaGentic harness — use 'audiagentic update' instead."
    if new_version_check not in source:
        source = _re.sub(
            r"[ \t]*// Start version check asynchronously\n"
            r"[ \t]*checkForNewPiVersion\(this\.version\)\.then\(\(\w+\) => \{\n"
            r"[ \t]*if \(\w+\) \{\n"
            r"[ \t]*this\.showNewVersionNotification\(\w+\);\n"
            r"[ \t]*\}\n"
            r"[ \t]*\}\);",
            new_version_check,
            source,
        )

    # Match the package-update block regardless of the callback variable name.
    new_pkg_check = "        // Package update notifications suppressed by AUDiaGentic harness."
    if new_pkg_check not in source:
        source = _re.sub(
            r"[ \t]*// Start package update check asynchronously\n"
            r"[ \t]*this\.checkForPackageUpdates\(\)\.then\(\(\w+\) => \{\n"
            r"[ \t]*if \(\w+\.length > 0\) \{\n"
            r"[ \t]*this\.showPackageUpdateNotification\(\w+\);\n"
            r"[ \t]*\}\n"
            r"[ \t]*\}\);",
            new_pkg_check,
            source,
        )

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


def _patch_mcp_explicit_config_only(npm_dir: Path) -> None:
    target = npm_dir / "node_modules" / "pi-mcp-adapter" / "config.ts"
    if not target.exists():
        return
    source = target.read_text(encoding="utf-8")
    marker = "if (overridePath) {\n"
    if marker in source:
        return
    needle = (
        "  const userPath = getPiGlobalConfigPath(overridePath);\n"
        "  const projectPath = getProjectConfigPath(cwd);\n"
    )
    replacement = (
        "  const userPath = getPiGlobalConfigPath(overridePath);\n"
        "  if (overridePath) {\n"
        "    return [{\n"
        "      id: \"pi-global\",\n"
        "      label: \"Pi explicit MCP config\",\n"
        "      readPath: userPath,\n"
        "      writePath: userPath,\n"
        "      kind: \"user\",\n"
        "      shared: false,\n"
        "      scope: \"global\",\n"
        "    }];\n"
        "  }\n"
        "  const projectPath = getProjectConfigPath(cwd);\n"
    )
    if needle in source:
        target.write_text(source.replace(needle, replacement, 1), encoding="utf-8")


def apply_lockdown_patches(npm_dir: Path, project_root: Path | None = None) -> None:
    pi_cfg = _c.load_pi_config(project_root=project_root)
    blocked = pi_cfg.get("lockdown", {}).get("block_builtin_commands", [])
    if blocked:
        _patch_slash_commands(npm_dir, blocked)
        _patch_interactive_mode(npm_dir, blocked)
        _c._print(f"Patched AudiaGentic agent: blocked commands {blocked}")
    if pi_cfg.get("ui", {}).get("hide_tool_use"):
        _patch_tool_execution(npm_dir)
        _c._print("Patched AudiaGentic agent: MCP tool call blocks hidden")
    _patch_update_notification(npm_dir)
    _c._print("Patched AudiaGentic agent: update notifications suppressed")
    _patch_mcp_oauth_suppress(npm_dir)
    _c._print("Patched MCP adapter: OAuth callback server suppressed (stdio servers only)")
    _patch_mcp_explicit_config_only(npm_dir)
    _c._print("Patched MCP adapter: explicit config disables auto-discovery")
    _patch_mcp_direct_tools_live_register(npm_dir)
    _c._print("Patched MCP adapter: bootstrapped direct tools register in-session")
    _patch_mcp_direct_tools_progress(npm_dir)
    _c._print("Patched MCP adapter: direct tool progress bridged to Pi")
    _patch_mcp_proxy_progress(npm_dir)
    _c._print("Patched MCP adapter: proxy tool progress bridged to Pi")
