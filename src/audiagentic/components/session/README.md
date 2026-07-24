# components/core/session/

Session and runtime control component.

## Intent

This area answers "what is current agent session running against?" and "what session-level controls can change without reinstalling project assets?"

## Capabilities

- Report harness, model, endpoint, environment, and auto-update status.
- Read materialized harness config.
- Toggle auto-update behavior.
- Refresh generated harness config.
- Trigger embedded rig update flows when harness runtime supports it.

## Key Files

- `session_api.py` public session API.
- `session_runtime_status.py` version/model/endpoint inspection.
- `session_embedded_rig.py` rig update workflow.
- `session_mcp.py` MCP wrapper.
