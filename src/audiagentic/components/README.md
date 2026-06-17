# components/

Installable AUDiaGentic capabilities.

## Intent

This layer turns shared infrastructure into user-facing component APIs and MCP servers.

- `core/` contains always-present project/session capabilities.
- `optional/` contains pluggable domains such as agent jobs, providers, ledger, release tooling, coding LSP, and source control.

## Design Boundary

Components should express behavior and orchestration for one product area. Generic helpers belong in `foundation/`. Durable state and install/update mechanics belong in `runtime/`.
