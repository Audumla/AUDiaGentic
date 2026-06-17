# runtime/harness/pi/

Pi harness adapter.

## Intent

Drive Pi-specific installation, runner command construction, system prompt shaping, and MCP config generation.

## Capabilities

- Format MCP config for Pi runtime.
- Render Pi-oriented system markdown and prompt material.
- Install/update Pi harness assets.
- Run Pi agent commands with shared context and constants.

This is current default harness path, so many session-level operations eventually flow through here.
