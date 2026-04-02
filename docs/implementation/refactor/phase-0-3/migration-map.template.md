# Migration Map Template

## Scope

- checkpoint date:
- owner:
- packet:

## Move Table

| Old Path | New Path | Move Type | Shim Required | Public Import Affected | Tests/Docs Impacted | Status | Notes |
|---|---|---|---|---|---|---|---|
| `src/...` | `src/...` | move/split/keep | yes/no | yes/no |  | planned |  |

## Legacy Path Notes

- legacy paths that must survive one checkpoint:
- legacy paths that can be rewritten immediately:
- approved shim pattern for this move set:

## Per-Slice Expected Baselines

| Slice | Expected outcome baseline | Notes |
|---|---|---|
| 12A | target scaffolding exists; shim placeholders exist; no business logic moved; import smoke unchanged |  |
| 12B | moved contracts/core/config modules no longer depend on their own legacy paths except via approved shims; no new forbidden dependency edges |  |
| 12C | lifecycle/release moves preserve baseline asset checks and release/bootstrap path resolution; no new forbidden dependency edges |  |
| 12D | execution/runtime moves preserve prompt bridge resolution and runtime/channel separation; no new forbidden dependency edges |  |
| 12E | channels/streaming/observability moves preserve control/telemetry boundaries and updated docs/tests/build references; no new forbidden dependency edges |  |

## Follow-up Inputs for PKT-FND-012 and PKT-FND-013

- risky moves:
- bulk import rewrite candidates:
- docs/config paths that must change:
- legacy paths expected to remain after each slice:
