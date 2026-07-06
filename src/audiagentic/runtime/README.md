# runtime/

Runtime infrastructure: packages that execute or observe live processes.

## Purpose

This layer owns code that turns packaged defaults plus installed components into a live working AUDiaGentic environment.

## Owns

- harness materialization, reload markers, system prompt assembly, and MCP config writes
- rig launch/reuse/probing for embedded and external backends
- read-only runtime environment facts (platform, process identity, live paths)
- package update detection and update prompts

## Subdomains

- `build/` build-time helpers
- `harness/` agent-facing runtime files, prompt assembly, and harness-specific adapters
- `rig/` model backend launch, registry, and HTTP probes
- `system/` read-only environment facts — importable from any layer
- `update/` version checks and update workflow helpers

## Must Not Own

- component lifecycle flows (→ `foundation/lifecycle`)
- durable job/session state (→ `components/agent_jobs`)
- provider-specific CLI integration logic
- release ledger business rules
- generic contracts, schemas, or workflow primitives

Those belong in `components/` or `foundation/`. The harness subscribes to
`lifecycle.component.*` events at module import time to react to component
install/enable/disable/uninstall — no capability registration is involved.
