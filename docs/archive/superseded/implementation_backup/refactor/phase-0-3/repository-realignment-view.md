# Repository Realignment View

## Purpose

This document is a working Phase 0.3 view of how the current repository should be realigned into the frozen repository-domain model.

It is not the final migration map and not the final inventory.
Its purpose is to:

- give `PKT-FND-010` a concrete starting view rather than a blank canvas
- show the recommended target domain for the major current roots
- identify areas that are cleanly mappable now
- identify areas that remain ambiguous and need explicit resolution in `PKT-FND-011`

## Current-to-target realignment view

| Current path/root | Recommended target domain/path | Realignment intent | Confidence | Ambiguity notes |
|---|---|---|---|---|
| `src/audiagentic/contracts/*` | `src/audiagentic/contracts/*` | keep as canonical contract root | high | minimal ambiguity |
| `src/audiagentic/cli/*` | `src/audiagentic/channels/cli/*` | treat CLI as a human-facing channel surface | high | keep entrypoints thin |
| `src/audiagentic/runtime/lifecycle/*` | `src/audiagentic/runtime/lifecycle/*` | move install/update/cutover/baseline behavior under runtime | high | legacy shim root may persist temporarily |
| `src/audiagentic/runtime/release/*` | `src/audiagentic/runtime/release/*` | place release/audit/bootstrap under runtime concerns | medium-high | some release APIs may also feel platform-wide; keep nested under runtime for this tranche |
| `src/audiagentic/execution/jobs/*` | mostly `src/audiagentic/execution/jobs/*` | job orchestration, records, packet running, approvals, reviews belong to execution | high | `session_input.py` stays here in first pass, but output adapters move under `streaming/` |
| `src/audiagentic/providers/*` | mostly `src/audiagentic/execution/providers/*` | provider selection/execution/adapters belong to execution | medium | streaming/progress/session pieces may later move or share seams with `streaming/` |
| `src/audiagentic/server/*` | `src/audiagentic/channels/server/*` | optional server is a channel surface | high | keep thin; do not let it own execution logic |
| `src/audiagentic/channels/discord/*` | `src/audiagentic/channels/discord/*` | Discord becomes a channel adapter in the repository-domain model | high | packet tracking may still refer to Discord separately |
| `tools/*` | `tools/*` entrypoints + reusable logic under `src/audiagentic/*` | keep `tools/` as deterministic visible wrapper root | high | some current tools may need internal library extraction |
| `tests/*` | `tests/*` mirrored to new domains | preserve centralized test root | high | test module paths will need remirroring |
| `src/audiagentic/contracts/schemas/*` | keep in place | remain canonical docs-owned schema location for this tranche | high | ownership only, not relocation |
| `docs/examples/*` | keep in place | remain canonical docs-owned example location for this tranche | high | ownership only, not relocation |
| `.github/workflows/*` | keep in place | managed baseline/workflow assets, not part of domain relocation | high | must stay visible to baseline checks |
| `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.clinerules*`, `.claude/`, `.agents/skills/` | keep in place | managed provider instruction assets; baseline-sensitive | high | path-sensitive during install/baseline sync |
| future `nodes/*` | `src/audiagentic/nodes/*` | reserved extension root, not folded into baseline domains in this tranche | high | conceptually aligns with runtime/channels later but path stays reserved now |
| future `discovery/*` | `src/audiagentic/discovery/*` | reserved extension root | high | keep parallel to repository domains |
| future `federation/*` | `src/audiagentic/federation/*` | reserved extension root | high | keep parallel to repository domains |
| future `connectors/*` | `src/audiagentic/connectors/*` | reserved extension root | high | keep parallel to repository domains |

## Recommended first-pass package landing map

```text
src/audiagentic/
  contracts/
  core/
  config/
  scoping/
  execution/
    jobs/
    providers/
  runtime/
    lifecycle/
    release/
    state/
  channels/
    cli/
    discord/
    server/
  streaming/
  observability/
  nodes/
  discovery/
  federation/
  connectors/
```

## Realignment rationale by area

### CLI

The CLI currently imports tool modules directly and also imports release and job entrypoints, which makes it a clear channel surface rather than a home for business logic. It should move conceptually to `channels/cli/` while keeping the actual console entrypoint thin. Observed in `src/audiagentic/channels/cli/main.py`. fileciteturn111file0

### Jobs / prompt launch

`src/audiagentic/execution/jobs/prompt_launch.py` is clearly execution-heavy: it builds job records, resolves providers/models, launches reviews, and persists launch/runtime artifacts under `.audiagentic/runtime/jobs/...`. That makes it primarily an `execution/jobs` concern with a secondary dependency on runtime persistence. fileciteturn112file0

### Lifecycle and release

The frozen Phase 0.3 model places durable project state, install/update/cutover behavior, and release/audit/bootstrap under `runtime/`. That means current `lifecycle/` and `release/` should be treated as runtime subdomains during the move rather than preserved as separate top-level canonical package roots.

### Providers

Provider adapters, selection, and execution wiring belong under `execution/providers/` in the first pass. However, provider session I/O and progress-capture behavior are one of the main ambiguity areas because they also touch the future `streaming/` domain.

### Server and Discord

Both are interaction surfaces. They should move under `channels/` and remain thin.

## Ambiguity list to resolve next

### 1. Prompt-trigger / bridge placement

Status:
- resolved for this tranche

Frozen decision:
- prompt-trigger bridge stays under `execution/jobs`
- prompt parser stays under `execution/jobs`
- no separate shared trigger-normalization domain or seam is required in Phase 0.3

Implementation note:
- any future extraction of generic alias/profile/schema helpers is optional follow-on cleanup, not part of the structural checkpoint

### 2. Session input / live interaction placement

Current concern:
- current `session_input.py` is under `jobs` and currently writes directly to runtime files on disk
- the desired future shape is to let session-input output attach through adapters rather than being hard-coded to disk

Frozen first-pass answer:
- `session_input.py` remains under `execution/jobs`
- session-input output must become adapter-driven rather than hard-coded to files
- streaming adapters live under `streaming/`
- a default disk adapter should preserve the current runtime-file behavior

Decision still needed:
- only the exact first-pass adapter interface and naming need to be frozen; the higher-level streaming unifier may be deferred to later follow-on work

### 3. Provider progress / streaming / completion boundaries

Frozen first-pass answer:
- provider execution remains in `execution/providers`
- move code as-is in the first pass rather than over-splitting immediately
- streaming transport or output adapters belong under `streaming/`
- telemetry/reporting belongs under `observability`

Remaining low-level ambiguity:
- whether helper modules such as the current shared provider streaming helper should move to `streaming/` in Phase 0.3 or remain temporarily colocated until the adapter pattern is in place

### 4. Runtime state versus execution records

Current concern:
- launch requests, subject manifests, and job runtime artifacts are persisted under `.audiagentic/runtime/jobs/...`, while orchestration lives under `jobs`

Likely first-pass answer:
- execution owns orchestration semantics
- runtime owns durable state layout and lifecycle/release concerns

Decision still needed:
- whether job-store and record-writing helpers remain under execution in this tranche or get split between `execution/jobs` and `runtime/state`
- whether the runtime path layout APIs should be centralized in `runtime/state` even if higher-level record creation stays under `execution/jobs`

### 5. Scoping domain scope

Current concern:
- the frozen target model includes `scoping`, but the current repository has no explicit `src/audiagentic/scoping/` root yet

Interpretation:
- `scoping/` is a code domain, not a documentation location
- it is intended for request/scope/plan-shaping logic, not for markdown specs or packet docs

Likely first-pass answer:
- create `scoping/` as a new reserved baseline code domain
- move only clearly scope/request/plan-shaping logic there when the inventory proves it exists cleanly

Decision still needed:
- whether scoping gets substantive code in Phase 0.3 or remains mostly a prepared root for later separation

### 6. Terminology blur

Frozen first-pass answer:
- do not rename terms in Phase 0.3
- capture terminology ambiguity during inventory for a later dedicated cleanup pass

## Immediate next actions

1. instantiate `repository-inventory.md` from the template
2. instantiate `migration-map.md` from the template
3. instantiate `ambiguity-report.md` from the template using the ambiguity list above as the seed
4. instantiate `public-import-surface.md` from the template
5. use those outputs to close the remaining freeze decisions in `PKT-FND-011`

## Proposed status of this document

Use this as a **seeded working view** for `PKT-FND-010`.
It should not replace the formal inventory, migration map, ambiguity report, or public-import-surface artifacts.
