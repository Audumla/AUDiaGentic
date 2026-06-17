# foundation/mcp/

Shared MCP server scaffolding.

## Intent

Give component MCP servers a common runtime shell so each component only defines tools, not transport plumbing.

## Capabilities

- Resolve server names from component YAML.
- Create FastMCP instances with standard instructions.
- Log tool calls without leaking arguments.
- Bridge blocking component work into MCP progress/log events.

Use this area when adding a new component MCP server or changing shared tool-call instrumentation behavior.
