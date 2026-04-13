# interoperability/protocols/acp/

## Status
**Scaffold only.** Reserved for the Agent Communication Protocol (ACP).
No executable code in this tranche.

## Purpose (when implemented)
ACP is a distinct inter-agent communication protocol, separate from the existing streaming
protocol. It is reserved here to prevent streaming from absorbing inter-agent messaging
ownership by default.

## What will belong here (when implemented)
- ACP message envelope and framing
- Agent-to-agent session negotiation
- ACP transport adapters

## What will NOT belong here
- Streaming sinks or event capture (→ `protocols/streaming/`)
- MCP protocol (→ `mcp/`)
- Job orchestration (→ `execution/jobs/`)

## Important distinction
`protocols/streaming/` owns the *provider output streaming* concern — capturing and normalizing
output from running AI providers. ACP owns *inter-agent communication* — messages between
agents at the protocol level. These must remain separate.

## Allowed Dependencies (when active)
- `foundation/contracts` — message schemas and canonical types
