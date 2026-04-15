---
id: standard-0010-python
label: Python MCP server development standard
state: ready
summary: Standard for Model Context Protocol (MCP) server implementation using Python frameworks like FastMCP.
request_refs: []
task_refs: []
standard_refs:
- standard-0010
---

# Standard

Default standard for Python-based MCP server development. Covers FastMCP patterns, optional component handling, and Python-specific implementation details.

# Source Basis

This standard is derived from:
- [Model Context Protocol Specification (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Best Practices Guide](https://modelcontextprotocol.info/docs/best-practices/)
- [FastMCP reference implementation](https://github.com/jlowin/fastmcp)
- [Official MCP Python SDK](https://modelcontextprotocol.io/docs/develop/build-server)
- Repository existing Python MCP implementations

# Requirements

1. All Python MCP servers must use FastMCP for transport (stdio, SSE, or configured transport) unless explicitly justified in the specification.

2. Server location must be determined by deployment model:
   - **`tools/mcp/{server-name}/`** — domain-focused servers deployed as standalone tools (single domain, specialized tools, separate lifecycle)
   - **`src/{package}/mcp_server.py`** — product-packaged servers deployed as part of main application package (broad domain coverage, distributed installation, shared lifecycle)

3. All MCP servers must have a single, clear purpose (single responsibility). Multi-domain servers must be explicitly justified in their specification and documentation.

4. Root discovery and project location detection must use a shared pattern to avoid duplication:
   ```python
   def get_project_root():
       if os.environ.get('AUDIAGENTIC_ROOT'):
           return Path(os.environ['AUDIAGENTIC_ROOT'])
       for parent in Path.cwd().parents:
           if (parent / '.audiagentic').exists():
               return parent
       return Path.cwd()
   ```

5. Optional component installation must be handled gracefully:
   ```python
   try:
       from advanced_feature import AdvancedFeature
       enable_advanced_features()
   except ImportError:
       logger.warning("Advanced features unavailable. Install with: pip install package[advanced-feature]")
   ```

6. Tool registration must follow FastMCP decorator pattern:
   ```python
   @mcp.tool(description="Perform a cost-effective lexical search")
   def search_lexical(query: str, limit: int = 10) -> list[dict]:
       """Search with minimal resource consumption."""
       # Implementation
   ```

7. Error handling must be structured and user-facing:
   ```python
   class ValidationError(Exception):
       def __init__(self, message: str, suggestions: list[str] | None = None):
           super().__init__(message)
           self.suggestions = suggestions or []
   ```

8. Instructions for the server must be defined in the FastMCP constructor:
   ```python
   mcp = FastMCP(
       name="knowledge-search",
       instructions=(
           "Read operations:"
           "- Lexical search (cheap)"
           "- Full-text analysis (expensive)"
           "Mutations:"
           "- Update page content"
           "Validation:"
           "- Check sync status"
       )
   )
   ```

9. Tool categorization must follow cost-aware patterns:
   - Read-only operations ordered by resource cost (lexical search before full-text analysis, scan before detailed retrieval)
   - Mutation operations grouped by domain (page operations, config operations, etc.)
   - Status and validation operations separated

10. Bootstrap logic and root discovery must execute before importing domain modules:
    ```python
    # Bootstrap first
    project_root = get_project_root()
    os.chdir(project_root)
    
    # Then imports
    from domain_logic import ComplexOperation
    ```

11. Testing must validate tool registration and MCP schema generation:
    ```python
    def test_tool_registration():
        server = get_mcp_server()
        tools = list(server._app.routes)  # or appropriate introspection
        assert len(tools) > 0
    ```

12. Servers must be compatible with FastMCP 3.0+ features (component versioning, granular authorization, OpenTelemetry instrumentation) or explicitly document version requirements.

# Default Rules

- Place servers in `tools/mcp/` for standalone, domain-specific servers.
- Place servers in `src/package/` only if the server is co-deployed with the main package.
- Prefer wrapping existing domain functions with `@mcp.tool()` decorators over reimplementing logic in the MCP layer.
- Extract root discovery and bootstrap into a shared module if used by multiple servers.
- Keep MCP validation and error handling lightweight; complex business logic belongs in the domain layer.
- Use `FastMCP(name, instructions=...)` constructor to document server capabilities clearly.
- Avoid duplicating root discovery, bootstrap, or configuration loading patterns across servers.
- Tests should verify tool registration, parameter validation, and error cases without a live MCP client.

# Verification Expectations

- All MCP servers must be tested for tool discovery and schema generation using the mcp CLI or test harness.
- Parameter type hints must match intended JSON Schema (document any edge cases).
- Error handling must be tested for clarity and actionability.
- Optional dependencies must be tested for both present and missing cases.
- Servers deployed in `tools/mcp/` should have a test entry point (e.g., `test_mcp_server.py`).
- Servers deployed in `src/package/` should include MCP tests in the package test suite.
- Root discovery and bootstrap must be tested across different working directories and environment configurations.

# Non-Goals

- Prescribing a single server architecture or layout for all MCP servers in the ecosystem.
- Replacing FastMCP's built-in validation or schema generation with custom implementations.
- Defining authorization or authentication policy (defer to FastMCP 3.0+ features and protocol spec).
- Mandating OpenTelemetry instrumentation (document support as optional capability).
- Enforcing specific prose style or documentation depth beyond what FastMCP requires.
