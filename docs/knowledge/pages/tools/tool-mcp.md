## Summary
The Model Context Protocol (MCP) server provides an interface for AI agents to interact with the AUDiaGentic knowledge component. It exposes capabilities for searching, querying, managing knowledge, and executing deterministic operations through a standardized protocol, enabling seamless agent integration.

## Current state
**MCP Server Implementation** (`tools/mcp/audiagentic-knowledge/mcp_server.py`):

**Exposed Tools:**

| Tool | Description |
|------|-------------|
| `knowledge_search_pages` | Lexical search across knowledge pages with metadata filters |
| `knowledge_get_page` | Retrieve full page content by ID |
| `knowledge_answer_question` | Deterministic-first QA over knowledge with optional LLM assistance |
| `knowledge_draft_sync_proposal` | Generate sync proposals for stale pages |
| `knowledge_generate_sync_proposals` | Generate sync proposals for all stale pages |
| `knowledge_list_profiles` | List configured LLM capability profiles |
| `knowledge_submit_profile_job` | Submit tasks to LLM provider layer |
| `knowledge_job` | Get job status or results |
| `knowledge_registry` | Registry operations (execution, importer, LLM, capability, navigation, actions, profiles, install, doctor, navigate) |
| `knowledge_run_action` | Execute deterministic actions |
| `knowledge_validate` | Validation operations (validate, status, drift) |
| `knowledge_seed_from_manifest` | Seed pages from import manifest |
| `knowledge_scaffold_page` | Create scaffold pages |
| `knowledge_events` | Event operations (scan, process, baseline) |
| `knowledge_bootstrap_project_knowledge` | Bootstrap project knowledge from manifest |
| `knowledge_index` | Index maintenance operations (maintain, validate, refresh) |

**Configuration:**
- Host profile: `mcp-stdio` (standard I/O transport)
- Configurable via `.audiagentic/knowledge/config/config.yml`
- Runtime settings in `runtime_contract` section

**Integration Points:**
- Agents connect via MCP stdio transport
- Tools map to knowledge component actions
- Results returned in MCP-standard format
- Supports both blocking and async modes

**Current Status:**
- Server implementation complete
- Tool registry configured
- Capability profile: `deterministic-minimal`
- LLM integration disabled by default

## How to use
**Starting the MCP Server:**

```bash
## Via launcher
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
    name="knowledge_search_pages",
    arguments={
        "query": "planning system",
        "limit": 10
    }
)

## Example: Search with metadata filters
result = mcp_client.call_tool(
    name="knowledge_search_pages",
    arguments={
        "filters": {"type": ["system", "guide"]},
        "limit": 20
    }
)

## Example: Get page content
result = mcp_client.call_tool(
    name="knowledge_get_page",
    arguments={
        "page_id": "system-planning"
    }
)

## Example: Answer question (deterministic)
result = mcp_client.call_tool(
    name="knowledge_answer_question",
    arguments={
        "question": "What are the planning artifact types?",
        "limit": 8,
        "allow_llm": false,
        "mode": "deterministic"
    }
)

## Example: Answer question (with LLM)
result = mcp_client.call_tool(
    name="knowledge_answer_question",
    arguments={
        "question": "How do I set up the development environment?",
        "limit": 8,
        "allow_llm": true,
        "mode": "blocking"
    }
)

## Example: Draft sync proposal
result = mcp_client.call_tool(
    name="knowledge_draft_sync_proposal",
    arguments={
        "page_id": "system-planning",
        "allow_llm": false,
        "mode": "deterministic"
    }
)

## Example: Generate all sync proposals
result = mcp_client.call_tool(
    name="knowledge_generate_sync_proposals",
    arguments={}
)

## Example: Validate vault
result = mcp_client.call_tool(
    name="knowledge_validate",
    arguments={
        "op": "validate"
    }
)

## Example: Get vault status
result = mcp_client.call_tool(
    name="knowledge_validate",
    arguments={
        "op": "status"
    }
)

## Example: Scan for drift
result = mcp_client.call_tool(
    name="knowledge_validate",
    arguments={
        "op": "drift"
    }
)

## Example: Process events
result = mcp_client.call_tool(
    name="knowledge_events",
    arguments={
        "op": "process"
    }
)

## Example: Scan events
result = mcp_client.call_tool(
    name="knowledge_events",
    arguments={
        "op": "scan"
    }
)

## Example: Record event baseline
result = mcp_client.call_tool(
    name="knowledge_events",
    arguments={
        "op": "baseline"
    }
)

## Example: Scaffold new page
result = mcp_client.call_tool(
    name="knowledge_scaffold_page",
    arguments={
        "page_id": "system-runtime",
        "title": "Runtime System",
        "page_type": "system",
        "summary": "Documentation for the runtime system",
        "owners": ["core-team"],
        "tags": ["runtime", "lifecycle"],
        "related": ["system-planning", "system-knowledge"]
    }
)

## Example: Registry operations
result = mcp_client.call_tool(
    name="knowledge_registry",
    arguments={
        "op": "execution"
    }
)

result = mcp_client.call_tool(
    name="knowledge_registry",
    arguments={
        "op": "doctor"
    }
)

result = mcp_client.call_tool(
    name="knowledge_registry",
    arguments={
        "op": "navigate",
        "goal": "find task templates",
        "limit": 5
    }
)

## Example: Run deterministic action
result = mcp_client.call_tool(
    name="knowledge_run_action",
    arguments={
        "action_id": "mark_stale_and_generate_sync_proposal",
        "arguments": {
            "page_id": "system-planning"
        }
    }
)

## Example: List LLM profiles
result = mcp_client.call_tool(
    name="knowledge_list_profiles",
    arguments={}
)

## Example: Submit profile job
result = mcp_client.call_tool(
    name="knowledge_submit_profile_job",
    arguments={
        "task_name": "summarize",
        "payload": {"text": "Content to summarize"},
        "mode": "async",
        "allow_llm": true
    }
)

## Example: Get job status
result = mcp_client.call_tool(
    name="knowledge_job",
    arguments={
        "op": "status",
        "job_id": "job-123"
    }
)

## Example: Get job result
result = mcp_client.call_tool(
    name="knowledge_job",
    arguments={
        "op": "result",
        "job_id": "job-123"
    }
)

## Example: Seed from manifest
result = mcp_client.call_tool(
    name="knowledge_seed_from_manifest",
    arguments={
        "manifest_path": "docs/knowledge/data/import/manifests/seed.yml",
        "record_sync": true,
        "update_existing": false
    }
)

## Example: Bootstrap project knowledge
result = mcp_client.call_tool(
    name="knowledge_bootstrap_project_knowledge",
    arguments={
        "manifest": "docs/knowledge/data/import/manifests/seed.yml",
        "allow_llm": false,
        "mode": "deterministic"
    }
)

## Example: Maintain index pages
result = mcp_client.call_tool(
    name="knowledge_index",
    arguments={
        "op": "maintain"
    }
)

## Example: Validate index links
result = mcp_client.call_tool(
    name="knowledge_index",
    arguments={
        "op": "validate"
    }
)

## Example: Refresh all indexes
result = mcp_client.call_tool(
    name="knowledge_index",
    arguments={
        "op": "refresh"
    }
)
```

**Available Tools Reference:**

| Tool | Key Arguments | Returns |
|------|---------------|---------|
| `knowledge_search_pages` | `query`, `filters`, `limit` | List of search results |
| `knowledge_get_page` | `page_id` | Full page with sections |
| `knowledge_answer_question` | `question`, `limit`, `allow_llm`, `mode` | Answer with sources |
| `knowledge_draft_sync_proposal` | `page_id`, `allow_llm`, `mode` | Sync proposal |
| `knowledge_generate_sync_proposals` | (none) | List of proposal paths |
| `knowledge_list_profiles` | (none) | List of profiles |
| `knowledge_submit_profile_job` | `task_name`, `payload`, `mode`, `allow_llm` | Job ID |
| `knowledge_job` | `op`, `job_id` | Status or result |
| `knowledge_registry` | `op`, `goal`, `limit` | Registry data |
| `knowledge_run_action` | `action_id`, `arguments` | Action result |
| `knowledge_validate` | `op` | Validation results |
| `knowledge_seed_from_manifest` | `manifest_path`, `record_sync`, `update_existing` | Seeded pages |
| `knowledge_scaffold_page` | `page_id`, `title`, `page_type`, `summary`, `owners`, `tags`, `related` | Created page |
| `knowledge_events` | `op` | Event results |
| `knowledge_bootstrap_project_knowledge` | `manifest`, `allow_llm`, `mode` | Bootstrap result |
| `knowledge_index` | `op` | Index maintenance result |

## Sync notes
This page should be refreshed when:
- New MCP tools are added
- Tool signatures change
- Server configuration options change
- MCP protocol version updates

**Sources:**
- `tools/mcp/audiagentic-knowledge/mcp_server.py` - Server implementation
- `tools/mcp/audiagentic-knowledge/launch_audiagentic_knowledge_mcp.py` - Launcher
- `.audiagentic/knowledge/config/config.yml` - Configuration
- MCP protocol specification

**Sync frequency:** On MCP server changes

## References
- [Knowledge System](../systems/system-knowledge.md)
- [CLI Tool](./tool-cli.md)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- MCP server source: `tools/mcp/audiagentic-knowledge/mcp_server.py`
