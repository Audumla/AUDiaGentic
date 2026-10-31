# components/core/session/

Session and runtime control component.

## Intent

This area answers "what is current agent session running against?" and "what session-level controls can change without reinstalling project assets?"

## Capabilities

- Report harness, model, endpoint, environment, and auto-update status.
- Read materialized harness config.
- Toggle auto-update behavior.
- Refresh generated harness config.

## Key Files

- `session_api.py` public session API.
- `session_runtime_status.py` version/model/endpoint inspection.
- `session_mcp.py` MCP wrapper.
