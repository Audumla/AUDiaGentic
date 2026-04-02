# Migration Map

## Scope

- checkpoint date: 2026-04-02
- owner: Phase 0.3 checkpoint
- packet: PKT-FND-010
- status: seeded working map

## Move Table

| Old Path | New Path | Move Type | Shim Required | Public Import Affected | Tests/Docs Impacted | Status | Notes |
|---|---|---|---|---|---|---|---|
| `src/audiagentic/cli/*` | `src/audiagentic/channels/cli/*` | move | yes | yes | yes | planned | keep console entrypoints thin |
| `src/audiagentic/lifecycle/*` | `src/audiagentic/runtime/lifecycle/*` | move | yes | yes | yes | planned | preserve baseline/install behavior |
| `src/audiagentic/release/*` | `src/audiagentic/runtime/release/*` | move | yes | yes | yes | planned | preserve release/bootstrap path resolution |
| `src/audiagentic/jobs/*` | `src/audiagentic/execution/jobs/*` | move | yes | yes | yes | planned | includes prompt bridge, prompt parser, prompt launch |
| `src/audiagentic/providers/*` | `src/audiagentic/execution/providers/*` | move | yes | yes | yes | planned | move intact first |
| `src/audiagentic/server/*` | `src/audiagentic/channels/server/*` | move | yes | yes | yes | planned | optional server remains channel-only |
| `src/audiagentic/overlay/discord/*` | `src/audiagentic/channels/discord/*` | move | yes | yes | yes | planned | channel adapter move |
| `session_input` output sinks | `src/audiagentic/streaming/adapters/*` | extract seam | n/a | no | yes | planned | default disk adapter preserves current behavior |
| `src/audiagentic/jobs/store.py` | later candidate: `src/audiagentic/runtime/state/jobs.py` | defer split | no | no | low | deferred | do not force split in structural checkpoint |
| persistence half of `src/audiagentic/jobs/reviews.py` | later candidate: `src/audiagentic/runtime/state/reviews.py` | defer split | no | no | low | deferred | keep file intact in first pass unless split becomes trivial |

## Legacy Path Notes

- legacy paths that must survive one checkpoint:
  - `src/audiagentic/cli/*`
  - `src/audiagentic/lifecycle/*`
  - `src/audiagentic/release/*`
  - `src/audiagentic/jobs/*`
  - `src/audiagentic/providers/*`
  - `src/audiagentic/server/*`
  - `src/audiagentic/overlay/discord/*`
- legacy paths that can be rewritten immediately:
  - internal-only imports not referenced by tracked docs, examples, workflows, tools, or install/baseline surfaces
- approved shim pattern for this move set:
  - forwarding/re-export shims from old package paths to new package paths
  - no dual live package structure
  - no new code may be added against legacy imports once `PKT-FND-012` begins

## Per-Slice Expected Baselines

| Slice | Expected outcome baseline | Notes |
|---|---|---|
| 12A | target scaffolding exists; shim placeholders exist; no business logic moved; import smoke unchanged | scaffolding only |
| 12B | moved contracts/core/config modules no longer depend on their own legacy paths except via approved shims; no new forbidden dependency edges | no schema/example path regressions |
| 12C | lifecycle/release moves preserve baseline asset checks and release/bootstrap path resolution; no new forbidden dependency edges | baseline-sensitive slice |
| 12D | execution/runtime moves preserve prompt bridge resolution; `session_input.py` still lives under execution/jobs; no new forbidden dependency edges | persistence splits still deferred |
| 12E | channels/streaming/observability moves preserve channel thinness and adapter boundaries; no new forbidden dependency edges | disk adapter available if adapter extraction begins |

## Follow-up Inputs for PKT-FND-012 and PKT-FND-013

- risky moves:
  - legacy public import roots under `jobs/*`, `providers/*`, `lifecycle/*`, `release/*`
  - Discord overlay move into channels
- bulk import rewrite candidates:
  - CLI imports of jobs/release modules
  - provider imports across legacy roots
- docs/config paths that must change:
  - documented package paths in implementation docs
  - examples referencing old import paths
- legacy paths expected to remain after each slice:
  - all public legacy roots remain shimmed until final cleanup
