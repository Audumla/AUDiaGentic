# components/source_control/

Source-control dependency and host-integration component.

## Intent

Provide minimal source-control introspection and bootstrap without embedding full git workflow logic in unrelated components.

## Capabilities

- Detect source-control availability and missing dependencies.
- Install or uninstall declared source-control tool dependencies through shared workflow steps.
- Expose source-control status through MCP and in-process API calls.
- Keep bootstrap/probe logic separate from higher-level release or job orchestration.

## Key Files

- `source_control_api.py` service entrypoint.
- `source_control_bootstrap.py` dependency declarations and availability checks.
- `probes.py` host detection helpers.
- `source_control_mcp.py` MCP wrapper.
