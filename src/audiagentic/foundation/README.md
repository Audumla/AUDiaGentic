# foundation/

Shared low-level primitives used by every higher layer.

## Purpose

Foundation is where AUDiaGentic keeps reusable building blocks that should stay stable across components and runtime implementations.

## Owns

- `components/` component descriptor models, registries, and dependency workflows
- `contracts/` schemas, canonical IDs, errors, and validation helpers
- `event/` generic envelopes, event bus, persistence, and replay
- `logging/` layered logging config, context propagation, and audit-log helpers
- `mcp/` shared MCP server scaffolding and output bridging
- `paths/` package, project, layered-path, and containment resolution
- `system/` process and host-level helpers
- `toolchains/` external dependency detection and recipe loading
- `workflow/` state-machine, transition, and propagation primitives

## Must Not Own

- provider-specific adapters
- project install state
- release lifecycle business logic
- user-facing component orchestration

If code needs project-specific state or external service behavior, it usually belongs above this layer.

## Root modules

The small number of modules at this package root are domain-neutral primitives
whose consumers span multiple foundation areas or components:

- `cli_io.py` terminal presentation at CLI boundaries
- `i18n.py` process-wide translation catalog
- `io.py` atomic and structured file I/O
- `registry_utils.py` generic typed registries
- `templates.py` dotted data-path rendering
- `time.py` UTC clock formatting

`refs.py` and `path_safety.py` do not belong at the root: declarative reference
resolution is owned by `config/`, and containment resolution is owned by
`paths/`. New root modules require an equally clear cross-cutting responsibility;
`system/` must not become a generic utilities folder.
