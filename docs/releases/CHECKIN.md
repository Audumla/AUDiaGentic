# Check-In Summary

Total changes: 12

- Delegated a real MA28 closeout to the OpenCode worker, verified its work, and recorded the result in the agent capability log.
- ACP/live-session support is now a declared, per-provider capability with honest support states (opencode largely working, codex in progress), so session features can be requested and tracked while they are being built out.
- Live agent sessions passed their end-to-end gate: conversations retain context across requests, closed and idle sessions reliably terminate their agent processes, and a streaming output-corruption bug found by the gate was fixed.
- Added real-subprocess tests for ACP session transport: fake agent fixture + 4 tests proving context retention and no-orphan guarantee
- Real-process testing of live agent sessions caught and fixed two subtle transport bugs: streamed agent messages could be lost at the end of a turn, and closing a session under timeout could corrupt the transport's shutdown.
- Added typed desired-state dataclasses and schemas for Codex and Pi Hindsight integration (MA26 step 2)
- Consolidated LSP MCP projection into the canonical managed-MCP family: coding-lsp now uses manage_mcp_entries with ownership scope 'coding-lsp/ag-lsp', replacing the duplicated lsp-mcp-projection family. Registry entries migrate automatically from legacy scope to scoped key for continuity.
- Plugin entry management now uses shared managed-config engine with ownership tracking; foreign entries are preserved on apply/prune operations.
- Long agent work sessions no longer lose the end of the agent's final report when event volume is high, and gateway sessions stopped buffering bulky raw event payloads nobody reads.
- Planned the migration from an in-process agent gateway to a self-managed machine-wide service, including safe multi-project execution and role-based capability launches, without expanding the existing agent-sessions plan into another catch-all.
- Tightened the shared-gateway roadmap so MCP and other transport modules remain logic-free adapters over reusable APIs, and added an architecture-enforcement item to prevent future layering drift.
- Added provider telemetry capability model and per-harness capability matrix documentation
