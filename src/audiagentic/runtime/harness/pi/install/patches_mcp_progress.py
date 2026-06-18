from __future__ import annotations

from pathlib import Path


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
