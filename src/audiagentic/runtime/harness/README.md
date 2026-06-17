# runtime/harness/

Harness materialization and runtime integration layer.

## Intent

Translate installed AUDiaGentic state into concrete agent-facing runtime files, prompts, MCP config, and reload markers.

## Capabilities

- Describe harness implementations and their config.
- Materialize system prompt and MCP configuration.
- Collect component-contributed MCP servers and harness instructions.
- Refresh or reload harness state after component changes.
- Route harness-specific helpers for Pi and OpenCode.

## Subareas

- `pi/` Pi-specific install, runner, prompt, and MCP formatting helpers.
- `opencode/` OpenCode-specific formatting and installer helpers.
- top-level modules handle shared harness descriptors, paths, reload markers, and rig integration.
