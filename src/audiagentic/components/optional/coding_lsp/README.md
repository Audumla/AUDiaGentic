# components/optional/coding_lsp/

Language-server integration component.

## Intent

Expose precise code-intelligence tools through AUDiaGentic-managed language server sessions.

## Capabilities

- Discover project root and active feature/binding LSP config.
- Add or remove enabled languages.
- Start, reuse, and shut down language server sessions.
- Provide workspace symbols, document symbols, definition, hover, references, rename preview, and diagnostics.
- Detect missing language-server binaries and install only dependencies for configured languages.

## Key Files

- `lsp_api.py` service API used by MCP and local callers.
- `lsp_session_manager.py` server session lifecycle and reuse.
- `runtime_resolver.py` active feature/binding server resolution.
- `coding_lsp_config.py` generated cache read/write and language detection.
- `language_registry.py` adapts registered language features into LSP runtime metadata and dependency mappings.
- `lsp_mcp.py` and `lsp_manage_mcp.py` tool wrappers.
