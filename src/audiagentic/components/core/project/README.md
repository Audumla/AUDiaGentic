# components/core/project/

Project management component.

## Intent

This area answers "what is installed in this repo?" and "how do components change project state?"

## Capabilities

- Report project/component install status.
- Install, uninstall, enable, and disable components.
- Read managed files under `.audiagentic/`.
- Return runtime-sync instructions so harness clients know whether to refresh, reload, or restart after component changes.

## Key Files

- `project_api.py` public entrypoint used by MCP wrappers and in-process callers.
- `project_components.py` component lifecycle operations and status assembly.
- `project_files.py` safe reads from managed project files.
- `project_mcp.py` MCP server wrapper for project tools.
