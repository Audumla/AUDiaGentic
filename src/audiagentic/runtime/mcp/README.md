# MCP Server Pattern

Component MCP servers are transport adapters only.

- Put core behavior in component APIs, for example `components/<name>/api.py` or `services/*`.
- Keep MCP server files limited to argument translation, `AUDIAGENTIC_REPO_ROOT` lookup, MCP descriptions, output bridging, and returning API results.
- Long-running tools accept a `ComponentOutputSink | None` callback and emit `ComponentOutputEvent`.
- MCP wrappers run blocking APIs through `run_blocking_with_output(...)` so events become standard `notifications/progress`.
- Diagnostic-only messages use `ComponentOutputEvent(kind="log", level="info" | "warning" | "error")`, which maps to MCP `notifications/message`.
- Do not scrape stdout for UI status when component APIs can emit structured events.
