from __future__ import annotations

from pathlib import Path


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
