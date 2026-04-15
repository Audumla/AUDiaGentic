## Summary
The Model Context Protocol (MCP) server provides an interface for AI agents to interact with the AUDiaGentic knowledge component. It exposes capabilities for searching, querying, and managing knowledge through a standardized protocol, enabling seamless agent integration.

## Current state
**MCP Server Implementation** (`tools/mcp/audiagentic-knowledge/mcp_server.py`):

**Exposed Tools:**
- `search_pages`: Lexical search across knowledge pages
- `get_page`: Retrieve full page content by ID
- `list_pages`: List pages with optional filtering
- `validate_vault`: Check knowledge vault integrity
- `scan_drift`: Detect drift between sources and pages
- `process_events`: Process pending events
- `scaffold_page`: Create new page templates

**Configuration:**
- Host profile: `mcp-stdio` (standard I/O transport)
- Configurable via `.audiagentic/knowledge/config.yml`
- Runtime settings in `runtime_contract` section

**Integration Points:**
- Agents connect via MCP stdio transport
- Tools map to knowledge component actions
- Results returned in MCP-standard format
- Supports both blocking and async modes

**Current Status:**
- Server implementation complete
- Tool registry configured
- Not actively deployed (capability profile: `deterministic-minimal`)
- LLM integration disabled by default

## How to use
**Starting the MCP Server:**

```bash

## Via CLI
python -m src.audiagentic.knowledge.cli --root . mcp-serve

## Or directly (via launcher)
python tools/mcp/audiagentic-knowledge/launch_audiagentic_knowledge_mcp.py
```

**Agent Configuration:**
Add to agent's MCP configuration:
```json
{
  "mcpServers": {
    "audiagentic-knowledge": {
      "command": "python",
      "args": [
        "tools/mcp/audiagentic-knowledge/launch_audiagentic_knowledge_mcp.py"
      ]
    }
  }
}
```

**Using MCP Tools:**

Agents can call tools through the MCP protocol:

```python

## Example: Search for pages
result = mcp_client.call_tool(
    name="search_pages",
    arguments={
        "query": "planning system",
        "limit": 10
    }
)

## Example: Get page content
result = mcp_client.call_tool(
    name="get_page",
    arguments={
        "page_id": "system-planning"
    }
)

## Example: Validate vault
result = mcp_client.call_tool(
    name="validate_vault",
    arguments={}
)
```

**Available Tools:**

| Tool | Description | Arguments |
|------|-------------|-----------|
| `search_pages` | Search pages by query | `query`, `limit` |
| `get_page` | Get page by ID | `page_id` |
| `list_pages` | List all pages | `page_type` (optional) |
| `validate_vault` | Validate vault integrity | none |
| `scan_drift` | Scan for source drift | none |
| `process_events` | Process pending events | none |
| `scaffold_page` | Create new page | `page_id`, `page_type`, `title`, `summary`, `owners` |

## Sync notes
This page should be refreshed when:
- New MCP tools are added
- Tool signatures change
- Server configuration options change
- MCP protocol version updates

**Sources:**
- `tools/mcp/audiagentic-knowledge/mcp_server.py` - Server implementation
- `tools/mcp/audiagentic-knowledge/launch_audiagentic_knowledge_mcp.py` - Launcher
- `.audiagentic/knowledge/config.yml` - Configuration
- MCP protocol specification

**Sync frequency:** On MCP server changes

## References
- [Knowledge System](../systems/system-knowledge.md)
- [CLI Tool](./tool-cli.md)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- MCP server source: `tools/mcp/audiagentic-knowledge/mcp_server.py`
