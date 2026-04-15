# AUDiaGentic Knowledge Component

This is an installable current-state knowledge capability intended for use inside any project.

## Runtime vs project ownership

Runtime-owned:
- CLI commands, validators, importer/action/execution defaults, MCP server, and host profiles.

Project-owned:
- the vault under `knowledge/`, sidecars, state, manifests, hooks, event adapters, and proposals.

## Contract

- Primary docs stay human-readable.
- Sidecar metadata and state live beside the docs under `knowledge/`.
- Behavior is driven from config at `.audiagentic/knowledge/config.yml`.
- Registries, hooks, navigation, manifests, and event adapters are all YAML-driven.
- Higher-level tasks use a deterministic execution registry first.
- Optional provider use is layered behind the deterministic contract and may remain disabled.
- This capability is aligned to the future `audiagentic knowledge ...` CLI shape even before the wider installer exists.

## First actions

1. Edit the import manifest under `knowledge/import/manifests/seed.yml`.
2. Edit hooks under `knowledge/sync/hooks.yml`.
3. Edit navigation routes under `knowledge/navigation/routes.yml`.
4. Edit registries under `knowledge/registries/`.
5. Run the CLI to seed, scan drift, process events, answer questions, and run `doctor`.
6. Rebind deterministic task handlers in `registries/execution.yml` before introducing any optional provider.
