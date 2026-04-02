# Migration Map

## Scope

- checkpoint date: 2026-04-02
- owner: Phase 0.3 checkpoint
- packet: PKT-FND-012 / PKT-FND-013
- status: code move complete; final validation in progress

## Move Table

| Old Path | New Path | Move Type | Shim Required | Public Import Affected | Tests/Docs Impacted | Status | Notes |
|---|---|---|---|---|---|---|---|
| `src/audiagentic/cli/*` | `src/audiagentic/channels/cli/*` | move + shim | yes | yes | yes | moved | canonical CLI entrypoint now lives under `channels/cli`; legacy `cli/main.py` remains a script-compatible shim |
| `src/audiagentic/lifecycle/*` | `src/audiagentic/runtime/lifecycle/*` | move + shim | yes | yes | yes | moved | lifecycle internals moved under `runtime/lifecycle`; legacy lifecycle modules forward to the new runtime modules |
| `src/audiagentic/release/*` | `src/audiagentic/runtime/release/*` | move + shim | yes | yes | yes | moved | release/bootstrap/audit internals moved under `runtime/release`; legacy release modules forward to the new runtime modules |
| `src/audiagentic/jobs/*` | `src/audiagentic/execution/jobs/*` | move + shim | yes | yes | yes | moved | prompt bridge, parser, launch, review, and state-machine logic now live under `execution/jobs`; legacy job modules remain forwarding shims |
| `src/audiagentic/providers/*` | `src/audiagentic/execution/providers/*` | move + shim | yes | yes | yes | moved | provider execution/status/adapter modules now live under `execution/providers`; config/catalog/registry helpers were rehomed to `config/*` |
| `src/audiagentic/server/*` | `src/audiagentic/channels/server/*` | move + shim | yes | yes | yes | moved | optional server seam now lives under `channels/server`; legacy server module remains a forwarding shim |
| `src/audiagentic/overlay/discord/*` | `src/audiagentic/channels/discord/*` | reserve compatibility root | yes | yes | yes | partial | no substantive Discord channel code moved in this tranche; reserved roots now exist in both locations for later channel work |
| `src/audiagentic/providers/streaming.py` | `src/audiagentic/streaming/provider_streaming.py` | move + shim | yes | yes | yes | moved | raw provider-stream helper moved under `streaming/`; legacy provider streaming module remains a forwarding shim |
| `session_input` output sinks | `src/audiagentic/streaming/adapters/*` | extract seam | n/a | no | yes | deferred | default disk-backed capture remains in place; adapter extraction is intentionally deferred beyond the structural checkpoint |
| `src/audiagentic/providers/config.py` | `src/audiagentic/config/provider_config.py` | move + shim | yes | yes | yes | moved | imports rewritten; legacy module is now a forwarding shim |
| `src/audiagentic/providers/catalog.py` | `src/audiagentic/config/provider_catalog.py` | move + shim | yes | yes | yes | moved | imports rewritten; legacy module is now a forwarding shim |
| `src/audiagentic/providers/registry.py` | `src/audiagentic/config/provider_registry.py` | move + shim | yes | yes | yes | moved | imports rewritten; legacy module is now a forwarding shim |
| `src/audiagentic/jobs/store.py` | later candidate: `src/audiagentic/runtime/state/jobs.py` | defer split | no | no | low | deferred | do not force split in structural checkpoint |
| persistence half of `src/audiagentic/jobs/reviews.py` | later candidate: `src/audiagentic/runtime/state/reviews.py` | defer split | no | no | low | deferred | keep file intact in first pass unless split becomes trivial |
| `.audiagentic/*.yaml` + `.audiagentic/prompts/*` | keep in place | preserve | no | yes | yes | frozen | installable baseline asset roots are path-sensitive and should not be relocated in this tranche |
| `.audiagentic/runtime/**` | keep in place, remain excluded from baseline sync | preserve/exclude | no | no | yes | frozen | runtime exclusion must continue to hold after the refactor |
| `docs/schemas/*`, `docs/examples/*` | keep in place | preserve | no | yes | yes | frozen | ownership may change, path does not |

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
  - any package references inside `.audiagentic/prompts/*` or managed instruction assets if they point to legacy roots
- legacy paths expected to remain after each slice:
  - all public legacy roots remain shimmed until final cleanup

## Checkpoint progress

- support scripts created for `PKT-FND-012`:
  - `tools/inventory_imports.py`
  - `tools/check_cross_domain_imports.py`
  - `tools/find_legacy_paths.py`
  - `tools/check_baseline_assets.py`
  - `tools/refactor_smoke.py`
- slice `12A` complete:
  - target domain package scaffolding created under `src/audiagentic/`
  - placeholder `__init__.py` files added for the new domain roots
  - legacy compatibility-root placeholders added for `cli`, `lifecycle`, `release`, `jobs`, `providers`, `server`, and `overlay/discord`
  - no business-logic modules moved yet
- slice `12B` initial pass complete:
  - stable provider config, catalog, and registry helpers moved into `src/audiagentic/config/*`
  - legacy `providers/config.py`, `providers/catalog.py`, and `providers/registry.py` now act as forwarding shims
  - imports were rewritten to the new config modules and targeted tests/refactor checks passed
- slice `12C` complete:
  - lifecycle modules moved into `src/audiagentic/runtime/lifecycle/*`
  - release modules moved into `src/audiagentic/runtime/release/*`
  - import rewrites and baseline-sensitive smoke checks passed
- slice `12D` complete:
  - job orchestration and provider execution modules moved into `src/audiagentic/execution/jobs/*` and `src/audiagentic/execution/providers/*`
  - legacy execution-facing roots remain as forwarding shims
  - prompt/bridge and provider smoke tests passed after import rewrites
- slice `12E` complete:
  - CLI and server channel entrypoints moved into `src/audiagentic/channels/*`
  - provider streaming helper moved into `src/audiagentic/streaming/provider_streaming.py`
  - current active docs/examples now point at canonical refactored paths
