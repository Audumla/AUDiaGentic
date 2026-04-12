# interoperability/mcp/

## Status
**Scaffold only.** Reserved for future MCP (Model Context Protocol) integration.
No executable code in this tranche.

## Planned Purpose
MCP client and server integration — enabling AUDiaGentic to expose its capabilities via the Model Context Protocol and to consume MCP servers as tool sources.

## What will belong here (when implemented)
- MCP client: connect to external MCP servers and expose their tools to execution
- MCP server: expose AUDiaGentic capabilities as an MCP server to other agents
- Protocol negotiation and capability exchange

## What will NOT belong here
- Provider-specific adapter logic (→ `providers/adapters/`)
- Streaming protocol (→ `protocols/streaming/`)
- Planning MCP tool surface (→ `tools/mcp/audiagentic-planning/` — this is a tools-layer concern, not a domain concern)

## Allowed Dependencies (when active)
- `foundation/contracts` — canonical types
- `execution/jobs` — to expose job launch as an MCP tool

## Related
- `tools/mcp/` — current MCP server implementation for the planning surface (tools layer)
- `interoperability/protocols/acp/` — separate protocol path (ACP vs MCP are distinct)
