from __future__ import annotations

import re
from pathlib import Path

from . import constants as _c


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

    # Constructor: hide audiagentic_ tools.
    ctor_injection = (
        "if (!toolDefinition || (toolName && toolName.startsWith('audiagentic_'))) "
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
        "        if (!(this.toolName && this.toolName.startsWith('audiagentic_'))) {\n"
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
    target = (
        _c._audiagentic_pkg_dir(npm_dir)
        / "dist" / "modes" / "interactive" / "interactive-mode.js"
    )
    if not target.exists():
        raise SystemExit(f"AudiaGentic agent install incomplete — not found: {target}")
    source = target.read_text(encoding="utf-8")

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


def apply_lockdown_patches(npm_dir: Path, project_root: Path | None = None) -> None:
    cfg = _c._load_config(project_root=project_root)
    blocked = cfg.get("lockdown", {}).get("block_builtin_commands", [])
    if blocked:
        _patch_slash_commands(npm_dir, blocked)
        _patch_interactive_mode(npm_dir, blocked)
        _c._print(f"Patched AudiaGentic agent: blocked commands {blocked}")
    if cfg.get("ui", {}).get("hide_tool_use"):
        _patch_tool_execution(npm_dir)
        _c._print("Patched AudiaGentic agent: MCP tool call blocks hidden")
    _patch_update_notification(npm_dir)
    _c._print("Patched AudiaGentic agent: update notifications suppressed")
    _patch_mcp_oauth_suppress(npm_dir)
    _c._print("Patched MCP adapter: OAuth callback server suppressed (stdio servers only)")
