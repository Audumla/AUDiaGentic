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

    helper_marker = "type DirectAutoAuthResult =\n"
    sync_helpers = (
        "type RuntimeSyncHint = {\n"
        "  target?: string;\n"
        "  action?: string;\n"
        "  reason?: string;\n"
        "  component_id?: string;\n"
        "};\n\n"
        "function getRuntimeSyncHint(result: { structuredContent?: unknown } | null | undefined): RuntimeSyncHint | undefined {\n"
        "  const structured = result?.structuredContent;\n"
        "  if (!structured || typeof structured !== \"object\" || Array.isArray(structured)) {\n"
        "    return undefined;\n"
        "  }\n"
        "  const sync = (structured as Record<string, unknown>).sync;\n"
        "  if (!sync || typeof sync !== \"object\" || Array.isArray(sync)) {\n"
        "    return undefined;\n"
        "  }\n"
        "  return sync as RuntimeSyncHint;\n"
        "}\n\n"
        "function formatRuntimeSyncNotice(sync: RuntimeSyncHint): string {\n"
        "  const component = typeof sync.component_id === \"string\" ? ` for component \\\"${sync.component_id}\\\"` : \"\";\n"
        "  switch (sync.action) {\n"
        "    case \"reload_required\":\n"
        "      return `AUDiaGentic runtime changed${component}. Reload Pi session to apply updates.`;\n"
        "    case \"restart_required\":\n"
        "      return `AUDiaGentic runtime changed${component}. Restart Pi session to apply updates.`;\n"
        "    case \"refresh_required\":\n"
        "    default:\n"
        "      return `AUDiaGentic runtime refreshed${component}.`;\n"
        "  }\n"
        "}\n\n"
    )
    if "type RuntimeSyncHint =" not in source and helper_marker in source:
        source = source.replace(helper_marker, sync_helpers + helper_marker, 1)
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

    sync_notice_marker = "      const result = await resultPromise;\n"
    sync_notice_new = (
        "      const sync = getRuntimeSyncHint(result as { structuredContent?: unknown });\n"
        "      if (sync && ctx?.hasUI) {\n"
        "        const notice = formatRuntimeSyncNotice(sync);\n"
        "        ctx.ui.notify(notice, sync.action === \"restart_required\" ? \"warning\" : \"info\");\n"
        "        ctx.ui.setStatus(\"audiagentic-runtime-action\", notice);\n"
        "      }\n"
    )
    # Old block with auto-reload setTimeout — revert to simple notify.
    sync_notice_old_complex = (
        "      const sync = getRuntimeSyncHint(result as { structuredContent?: unknown });\n"
        "      if (sync) {\n"
        "        if (sync.action === \"restart_required\") {\n"
        "          if (ctx?.hasUI) {\n"
        "            const notice = formatRuntimeSyncNotice(sync);\n"
        "            ctx.ui.notify(notice, \"warning\");\n"
        "            ctx.ui.setStatus(\"audiagentic-runtime-action\", notice);\n"
        "          }\n"
        "        } else if (sync.action === \"reload_required\" && ctx?.reload) {\n"
        "          if (ctx.hasUI) ctx.ui.setStatus(\"audiagentic-runtime-action\", \"AUDiaGentic runtime updated — reloading...\");\n"
        "          setTimeout(async () => {\n"
        "            try { await ctx.reload(); } catch { /* ctx may be stale if another reload already ran */ }\n"
        "          }, 1500);\n"
        "        } else if (sync.action !== \"reload_required\" && ctx?.hasUI) {\n"
        "          ctx.ui.notify(formatRuntimeSyncNotice(sync), \"info\");\n"
        "          ctx.ui.setStatus(\"audiagentic-runtime-action\", formatRuntimeSyncNotice(sync));\n"
        "        }\n"
        "      }\n"
    )
    if sync_notice_new not in source:
        if sync_notice_old_complex in source:
            source = source.replace(sync_notice_old_complex, sync_notice_new, 1)
        elif sync_notice_marker in source:
            source = source.replace(sync_notice_marker, sync_notice_marker + sync_notice_new, 1)

    success_details_old = '        details: { server: spec.serverName, tool: spec.originalName, uiOpen: true },\n'
    success_details_new = (
        '        details: { server: spec.serverName, tool: spec.originalName, uiOpen: true, '
        'mcpResult: result, sync },\n'
    )
    if success_details_new not in source and success_details_old in source:
        source = source.replace(success_details_old, success_details_new, 1)

    plain_details_old = '        details: { server: spec.serverName, tool: spec.originalName },\n'
    plain_details_new = (
        '        details: { server: spec.serverName, tool: spec.originalName, mcpResult: result, sync },\n'
    )
    if plain_details_new not in source and plain_details_old in source:
        source = source.replace(plain_details_old, plain_details_new, 1)

    error_details_old = '          details: { error: "tool_error", server: spec.serverName },\n'
    error_details_new = (
        '          details: { error: "tool_error", server: spec.serverName, mcpResult: result, sync },\n'
    )
    if error_details_new not in source and error_details_old in source:
        source = source.replace(error_details_old, error_details_new, 1)

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


def _patch_mcp_proxy_progress(npm_dir: Path) -> None:
    """Bridge MCP progress notifications for generic `mcp(...)` calls too."""
    proxy_target = npm_dir / "node_modules" / "pi-mcp-adapter" / "proxy-modes.ts"
    index_target = npm_dir / "node_modules" / "pi-mcp-adapter" / "index.ts"
    if not proxy_target.exists() or not index_target.exists():
        return

    proxy_source = proxy_target.read_text(encoding="utf-8")

    old_import = 'import { authenticate, supportsOAuth } from "./mcp-auth-flow.ts";'
    new_import = (
        'import { authenticate, supportsOAuth } from "./mcp-auth-flow.ts";\n'
        'import { LoggingMessageNotificationSchema } from "@modelcontextprotocol/sdk/types.js";'
    )
    if "LoggingMessageNotificationSchema" not in proxy_source and old_import in proxy_source:
        proxy_source = proxy_source.replace(old_import, new_import, 1)

    old_sig = (
        "export async function executeCall(\n"
        "  state: McpExtensionState,\n"
        "  toolName: string,\n"
        "  args?: Record<string, unknown>,\n"
        "  serverOverride?: string,\n"
        "  getPiTools?: () => ToolInfo[] | undefined,\n"
        "): Promise<ProxyToolResult> {"
    )
    new_sig = (
        "export async function executeCall(\n"
        "  state: McpExtensionState,\n"
        "  toolName: string,\n"
        "  args?: Record<string, unknown>,\n"
        "  serverOverride?: string,\n"
        "  getPiTools?: () => ToolInfo[] | undefined,\n"
        "  onUpdate?: ((update: AgentToolResult<Record<string, unknown>>) => void) | undefined,\n"
        "  ctx?: { ui?: { setWorkingVisible?: (visible: boolean) => void; setWorkingMessage?: (message?: string) => void; setStatus?: (key: string, value?: string) => void } } | undefined,\n"
        "): Promise<ProxyToolResult> {"
    )
    if "onUpdate?: ((update: AgentToolResult<Record<string, unknown>>) => void) | undefined," not in proxy_source and old_sig in proxy_source:
        proxy_source = proxy_source.replace(old_sig, new_sig, 1)

    call_marker = "    const resultPromise = connection.client.callTool({\n"
    progress_block = (
        "    connection.client.setNotificationHandler(LoggingMessageNotificationSchema, (notification) => {\n"
        "      const data = notification.params.data;\n"
        "      const message = typeof data === \"object\" && data !== null && \"message\" in data\n"
        "        ? String((data as { message?: unknown }).message)\n"
        "        : typeof data === \"string\"\n"
        "          ? data\n"
        "          : JSON.stringify(data);\n"
        "      const text = `[${notification.params.level}] ${message}`;\n"
        "      ctx?.ui?.setWorkingVisible?.(true);\n"
        "      ctx?.ui?.setWorkingMessage?.(text);\n"
        "      ctx?.ui?.setStatus?.(\"mcp-progress\", text);\n"
        "      onUpdate?.({\n"
        "        content: [{ type: \"text\" as const, text }],\n"
        "        details: { mode: \"call\", server: serverName, tool: toolMeta?.originalName ?? toolName, log: notification.params },\n"
        "      });\n"
        "    });\n\n"
        "    const resultPromise = connection.client.callTool(\n"
        "      {\n"
        "        name: toolMeta.originalName,\n"
        "        arguments: args ?? {},\n"
        "        _meta: uiSession?.requestMeta,\n"
        "      },\n"
        "      undefined,\n"
        "      {\n"
        "        resetTimeoutOnProgress: true,\n"
        "        onprogress: (progress) => {\n"
        "          const message = typeof progress.message === \"string\"\n"
        "            ? progress.message\n"
        "            : `MCP progress${typeof progress.progress === \"number\" ? ` ${progress.progress}` : \"\"}`;\n"
        "          ctx?.ui?.setWorkingVisible?.(true);\n"
        "          ctx?.ui?.setWorkingMessage?.(message);\n"
        "          ctx?.ui?.setStatus?.(\"mcp-progress\", message);\n"
        "          onUpdate?.({\n"
        "            content: [{ type: \"text\" as const, text: message }],\n"
        "            details: { mode: \"call\", server: serverName, tool: toolMeta.originalName, progress },\n"
        "          });\n"
        "        },\n"
        "      },\n"
        "    );"
    )
    old_call = (
        "    const resultPromise = connection.client.callTool({\n"
        "      name: toolMeta.originalName,\n"
        "      arguments: args ?? {},\n"
        "      _meta: uiSession?.requestMeta,\n"
        "    });"
    )
    if "resetTimeoutOnProgress: true" not in proxy_source and old_call in proxy_source:
        proxy_source = proxy_source.replace(old_call, progress_block, 1)

    finally_marker = "  } finally {\n"
    finally_inserts = (
        "  } finally {\n"
        "    connection?.client?.removeNotificationHandler?.(LoggingMessageNotificationSchema);\n"
        "    ctx?.ui?.setWorkingMessage?.();\n"
        "    ctx?.ui?.setStatus?.(\"mcp-progress\", undefined);\n"
    )
    if "removeNotificationHandler?.(LoggingMessageNotificationSchema)" not in proxy_source and finally_marker in proxy_source:
        proxy_source = proxy_source.replace(finally_marker, finally_inserts, 1)

    if proxy_source != proxy_target.read_text(encoding="utf-8"):
        proxy_target.write_text(proxy_source, encoding="utf-8")

    index_source = index_target.read_text(encoding="utf-8")
    old_execute = "          return executeCall(state, params.tool, parsedArgs, params.server, getPiTools);\n"
    new_execute = "          return executeCall(state, params.tool, parsedArgs, params.server, getPiTools, _onUpdate, _ctx);\n"
    if new_execute not in index_source and old_execute in index_source:
        index_source = index_source.replace(old_execute, new_execute, 1)
    if index_source != index_target.read_text(encoding="utf-8"):
        index_target.write_text(index_source, encoding="utf-8")


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
