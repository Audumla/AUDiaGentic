# components/optional/coding_lsp/

Language-server integration component.

## Intent

Expose precise code-intelligence tools through AUDiaGentic-managed language server sessions.

## Capabilities

- Discover project root and active `lsp.json` config.
- Add or remove enabled languages.
- Start, reuse, and shut down language server sessions.
- Provide workspace symbols, document symbols, definition, hover, references, rename preview, and diagnostics.
- Detect missing language-server binaries and install only dependencies for configured languages.

## Key Files

- `lsp_api.py` service API used by MCP and local callers.
- `lsp_session_manager.py` server session lifecycle and reuse.
- `coding_lsp_config.py` config read/write and language detection.
- `language_registry.py` supported language metadata and dependency mapping.
- `lsp_mcp.py` and `lsp_manage_mcp.py` tool wrappers.
