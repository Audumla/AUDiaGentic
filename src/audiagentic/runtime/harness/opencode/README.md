# runtime/harness/opencode/

OpenCode harness adapter.

## Intent

Package shared AUDiaGentic runtime state into shapes expected by OpenCode.

## Capabilities

- MCP config formatting for OpenCode.
- Installer constants and runtime-specific bootstrap helpers.
- Runner integration points for OpenCode session execution.

This area is intentionally small because most harness-generic behavior stays in `runtime/harness/`.
