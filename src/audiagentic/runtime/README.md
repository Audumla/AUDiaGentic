# runtime/

Runtime infrastructure and mutable project state.

## Purpose

This layer owns code that turns packaged defaults plus installed components into a live working AUDiaGentic environment.

## Owns

- lifecycle install, detect, baseline sync, and uninstall flows
- layered config loading from package, user, and project tiers
- harness materialization, reload markers, system prompt assembly, and MCP config writes
- rig launch/reuse/probing for embedded and external backends
- durable job/session state stores
- package update detection and update prompts

## Subdomains

- `config/` layered YAML loading helpers
- `harness/` agent-facing runtime files, prompt assembly, and harness-specific adapters
- `lifecycle/` install/detect/sync/uninstall logic
- `rig/` model backend launch, registry, and HTTP probes
- `state/` persistent job/session input storage
- `update/` version checks and update workflow helpers

## Must Not Own

- provider-specific CLI integration logic
- release ledger business rules
- generic contracts, schemas, or workflow primitives

Those belong in `components/` or `foundation/`.
