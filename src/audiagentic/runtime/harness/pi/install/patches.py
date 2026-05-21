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


def _patch_mcp_direct_tools_live_register(npm_dir: Path) -> None:
    """Register bootstrapped direct MCP tools immediately in-session.

    Upstream adapter populates metadata cache for newly configured direct-tool
    servers during `session_start`, but only shows a "available after restart"
    notice. We patch that path to register the newly discovered direct tools
    immediately so they can be used on the next turn without a full restart.
    """
    target = npm_dir / "node_modules" / "pi-mcp-adapter" / "init.ts"
    if not target.exists():
        return

    source = target.read_text(encoding="utf-8")

    old_import = 'import { getMissingConfiguredDirectToolServers } from "./direct-tools.ts";'
    new_import = (
        'import { createDirectToolExecutor, getMissingConfiguredDirectToolServers, resolveDirectTools } '
        'from "./direct-tools.ts";'
    )
    if new_import not in source and old_import in source:
        source = source.replace(old_import, new_import, 1)

    if 'import { Type } from "typebox";' not in source:
        marker = 'import { existsSync } from "node:fs";'
        if marker in source:
            source = source.replace(marker, marker + '\nimport { Type } from "typebox";', 1)

    if 'import { renderMcpToolResult } from "./tool-result-renderer.ts";' not in source:
        marker = 'import { logger } from "./logger.ts";'
        if marker in source:
            source = source.replace(
                marker,
                marker + '\nimport { renderMcpToolResult } from "./tool-result-renderer.ts";',
                1,
            )

    old_block = (
        "      const bootstrapped = bootstrapResults.filter(r => r.ok).map(r => r.name);\n"
        "      if (bootstrapped.length > 0 && ctx.hasUI) {\n"
        '        ctx.ui.notify(`MCP: direct tools for ${bootstrapped.join(", ")} will be available after restart`, "info");\n'
        "      }"
    )
    new_block = (
        "      const bootstrapped = bootstrapResults.filter(r => r.ok).map(r => r.name);\n"
        "      if (bootstrapped.length > 0) {\n"
        "        const updatedCache = loadMetadataCache();\n"
        "        const bootstrappedSpecs = resolveDirectTools(config, updatedCache, prefix)\n"
        "          .filter(spec => bootstrapped.includes(spec.serverName));\n"
        "        for (const spec of bootstrappedSpecs) {\n"
        "          (pi.registerTool as (tool: unknown) => unknown)({\n"
        "            name: spec.prefixedName,\n"
        '            label: `MCP: ${spec.originalName}`,\n'
        '            description: spec.description || "(no description)",\n'
        '            parameters: Type.Unsafe((spec.inputSchema || { type: "object", properties: {} }) as never),\n'
        "            execute: createDirectToolExecutor(() => state, () => Promise.resolve(state), spec),\n"
        "            renderResult: renderMcpToolResult,\n"
        "          });\n"
        "        }\n"
        "        if (ctx.hasUI) {\n"
        '          ctx.ui.notify(`MCP: direct tools for ${bootstrapped.join(", ")} are now available`, "info");\n'
        "        }\n"
        "      }"
    )
    if new_block not in source and old_block in source:
        source = source.replace(old_block, new_block, 1)

    target.write_text(source, encoding="utf-8")


def _patch_mcp_direct_tools_progress(npm_dir: Path) -> None:
    """Bridge MCP progress notifications into Pi tool updates.

    The MCP SDK only requests `notifications/progress` when `onprogress` is
    supplied on the request. This keeps long-running tool calls request-scoped
    and lets Pi render compact status without scraping subprocess output.
    """
    target = npm_dir / "node_modules" / "pi-mcp-adapter" / "direct-tools.ts"
    if not target.exists():
        return

    source = target.read_text(encoding="utf-8")
    old_signature = "  return async function execute(_toolCallId, params) {"
    new_signature = "  return async function execute(_toolCallId, params, _signal, onUpdate, ctx) {"
    if new_signature not in source and old_signature in source:
        source = source.replace(old_signature, new_signature, 1)

    old_import = 'import { authenticate, supportsOAuth } from "./mcp-auth-flow.ts";'
    new_import = (
        'import { authenticate, supportsOAuth } from "./mcp-auth-flow.ts";\n'
        'import { LoggingMessageNotificationSchema } from "@modelcontextprotocol/sdk/types.js";'
    )
    if "LoggingMessageNotificationSchema" not in source and old_import in source:
        source = source.replace(old_import, new_import, 1)

    old = (
        "      const resultPromise = connection.client.callTool({\n"
        "        name: spec.originalName,\n"
        "        arguments: params ?? {},\n"
        "        _meta: uiSession?.requestMeta,\n"
        "      });"
    )
    new = (
        "      const resultPromise = connection.client.callTool(\n"
        "        {\n"
        "          name: spec.originalName,\n"
        "          arguments: params ?? {},\n"
        "          _meta: uiSession?.requestMeta,\n"
        "        },\n"
        "        undefined,\n"
        "        {\n"
        "          resetTimeoutOnProgress: true,\n"
        "          onprogress: (progress) => {\n"
        "            const message = typeof progress.message === \"string\"\n"
        "              ? progress.message\n"
        "              : `MCP progress${typeof progress.progress === \"number\" ? ` ${progress.progress}` : \"\"}`;\n"
        "            ctx?.ui?.setWorkingVisible?.(true);\n"
        "            ctx?.ui?.setWorkingMessage?.(message);\n"
        "            ctx?.ui?.setStatus?.(\"mcp-progress\", message);\n"
        "            onUpdate?.({\n"
        "              content: [{ type: \"text\" as const, text: message }],\n"
        "              details: { server: spec.serverName, tool: spec.originalName, progress },\n"
        "            });\n"
        "          },\n"
        "        },\n"
        "      );"
    )
    if new not in source and old in source:
        source = source.replace(old, new, 1)
    elif "ctx?.ui?.setStatus?.(\"mcp-progress\", message);" not in source:
        source = source.replace(
            "            onUpdate?.({\n"
            "              content: [{ type: \"text\" as const, text: message }],",
            "            ctx?.ui?.setStatus?.(\"mcp-progress\", message);\n"
            "            onUpdate?.({\n"
            "              content: [{ type: \"text\" as const, text: message }],",
            1,
        )
    elif "ctx?.ui?.setWorkingMessage?.(message);" not in source:
        source = source.replace(
            "            ctx?.ui?.setStatus?.(\"mcp-progress\", message);",
            "            ctx?.ui?.setWorkingVisible?.(true);\n"
            "            ctx?.ui?.setWorkingMessage?.(message);\n"
            "            ctx?.ui?.setStatus?.(\"mcp-progress\", message);",
            1,
        )

    log_handler = (
        "      connection.client.setNotificationHandler(LoggingMessageNotificationSchema, (notification) => {\n"
        "        const data = notification.params.data;\n"
        "        const message = typeof data === \"object\" && data !== null && \"message\" in data\n"
        "          ? String((data as { message?: unknown }).message)\n"
        "          : typeof data === \"string\"\n"
        "            ? data\n"
        "            : JSON.stringify(data);\n"
        "        const text = `[${notification.params.level}] ${message}`;\n"
        "        ctx?.ui?.setWorkingVisible?.(true);\n"
        "        ctx?.ui?.setWorkingMessage?.(text);\n"
        "        ctx?.ui?.setStatus?.(\"mcp-progress\", text);\n"
        "        onUpdate?.({\n"
        "          content: [{ type: \"text\" as const, text }],\n"
        "          details: { server: spec.serverName, tool: spec.originalName, log: notification.params },\n"
        "        });\n"
        "      });\n\n"
    )
    call_marker = "      const resultPromise = connection.client.callTool(\n"
    if "connection.client.setNotificationHandler(LoggingMessageNotificationSchema" not in source and call_marker in source:
        source = source.replace(call_marker, log_handler + call_marker, 1)
    elif "ctx?.ui?.setWorkingMessage?.(text);" not in source:
        source = source.replace(
            "        ctx?.ui?.setStatus?.(\"mcp-progress\", text);",
            "        ctx?.ui?.setWorkingVisible?.(true);\n"
            "        ctx?.ui?.setWorkingMessage?.(text);\n"
            "        ctx?.ui?.setStatus?.(\"mcp-progress\", text);",
            1,
        )

    finally_marker = "    } finally {\n"
    clear_status = "      ctx?.ui?.setStatus?.(\"mcp-progress\", undefined);\n"
    if clear_status not in source and finally_marker in source:
        source = source.replace(finally_marker, finally_marker + clear_status, 1)
    clear_working = "      ctx?.ui?.setWorkingMessage?.();\n"
    if clear_working not in source and finally_marker in source:
        source = source.replace(finally_marker, finally_marker + clear_working, 1)
    remove_log_handler = "      connection?.client?.removeNotificationHandler?.(LoggingMessageNotificationSchema);\n"
    if remove_log_handler not in source and finally_marker in source:
        source = source.replace(finally_marker, finally_marker + remove_log_handler, 1)

    if source != target.read_text(encoding="utf-8"):
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
    _patch_mcp_direct_tools_live_register(npm_dir)
    _c._print("Patched MCP adapter: bootstrapped direct tools register in-session")
    _patch_mcp_direct_tools_progress(npm_dir)
    _c._print("Patched MCP adapter: direct tool progress bridged to Pi")
