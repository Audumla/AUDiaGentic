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
| `src/audiagentic/lifecycle/*` | `src/audiagentic/runtime/lifecycle/*` | move install/update/cutover/baseline behavior under runtime | high | legacy shim root may persist temporarily |
| `src/audiagentic/release/*` | `src/audiagentic/runtime/release/*` | place release/audit/bootstrap under runtime concerns | medium-high | some release APIs may also feel platform-wide; keep nested under runtime for this tranche |
| `src/audiagentic/jobs/*` | mostly `src/audiagentic/execution/jobs/*` | job orchestration, records, packet running, approvals, reviews belong to execution | medium | session input and some runtime-persistence helpers may split later |
| `src/audiagentic/providers/*` | mostly `src/audiagentic/execution/providers/*` | provider selection/execution/adapters belong to execution | medium | streaming/progress/session pieces may later move or share seams with `streaming/` |
| `src/audiagentic/server/*` | `src/audiagentic/channels/server/*` | optional server is a channel surface | high | keep thin; do not let it own execution logic |
| `src/audiagentic/overlay/discord/*` | `src/audiagentic/channels/discord/*` | Discord becomes a channel adapter in the repository-domain model | high | packet tracking may still refer to Discord separately |
| `tools/*` | `tools/*` entrypoints + reusable logic under `src/audiagentic/*` | keep `tools/` as deterministic visible wrapper root | high | some current tools may need internal library extraction |
| `tests/*` | `tests/*` mirrored to new domains | preserve centralized test root | high | test module paths will need remirroring |
| `docs/schemas/*` | keep in place | remain canonical docs-owned schema location for this tranche | high | ownership only, not relocation |
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

The CLI currently imports tool modules directly and also imports release and job entrypoints, which makes it a clear channel surface rather than a home for business logic. It should move conceptually to `channels/cli/` while keeping the actual console entrypoint thin. Observed in `src/audiagentic/cli/main.py`. fileciteturn111file0

### Jobs / prompt launch

`src/audiagentic/jobs/prompt_launch.py` is clearly execution-heavy: it builds job records, resolves providers/models, launches reviews, and persists launch/runtime artifacts under `.audiagentic/runtime/jobs/...`. That makes it primarily an `execution/jobs` concern with a secondary dependency on runtime persistence. fileciteturn112file0

### Lifecycle and release

The frozen Phase 0.3 model places durable project state, install/update/cutover behavior, and release/audit/bootstrap under `runtime/`. That means current `lifecycle/` and `release/` should be treated as runtime subdomains during the move rather than preserved as separate top-level canonical package roots.

### Providers

Provider adapters, selection, and execution wiring belong under `execution/providers/` in the first pass. However, provider session I/O and progress-capture behavior are one of the main ambiguity areas because they also touch the future `streaming/` domain.

### Server and Discord

Both are interaction surfaces. They should move under `channels/` and remain thin.

## Ambiguity list to resolve next

### 1. Prompt-trigger / bridge placement

Current concern:
- bridge and trigger behavior spans CLI, jobs, providers, and tool wrappers

Likely first-pass answer:
- keep canonical orchestration in `execution/jobs`
- keep surfaces thin under `channels/cli` or future channel adapters
- keep wrappers in `tools/` thin only

Decision still needed:
- whether any shared trigger-normalization helpers deserve a `core/` or `config/` seam rather than living entirely under execution

### 2. Session input / live interaction placement

Current concern:
- current session input handling is under `jobs`, but shared provider-session I/O is one of the reasons `streaming/` exists as a target domain

Likely first-pass answer:
- keep existing logic operationally under `execution/jobs` during the initial move
- move only clearly stream-oriented helpers toward `streaming/` once seams are explicit

Decision still needed:
- what minimum code qualifies as `streaming` in Phase 0.3 versus later follow-on refactors

### 3. Provider progress / streaming / completion boundaries

Current concern:
- provider execution, progress capture, streaming, and structured completion are closely related but should not collapse into one catch-all domain

Likely first-pass answer:
- provider execution remains in `execution/providers`
- stream transport and live I/O orchestration align with `streaming`
- telemetry/reporting aligns with `observability`

Decision still needed:
- whether any current provider helper modules should be split in Phase 0.3 or merely relocated intact first

### 4. Runtime state versus execution records

Current concern:
- launch requests, subject manifests, and job runtime artifacts are persisted under `.audiagentic/runtime/jobs/...`, while orchestration lives under `jobs`

Likely first-pass answer:
- execution owns orchestration semantics
- runtime owns durable state layout and lifecycle/release concerns

Decision still needed:
- whether job-store and record-writing helpers remain under execution in this tranche or get split between `execution/jobs` and `runtime/state`

### 5. Scoping domain scope

Current concern:
- the frozen target model includes `scoping`, but the current repository has no explicit `src/audiagentic/scoping/` root yet

Likely first-pass answer:
- create `scoping/` as a new reserved baseline domain
- move only clearly scope/request/plan shaping logic there when the inventory proves it exists cleanly

Decision still needed:
- whether scoping gets substantive code in Phase 0.3 or remains mostly a prepared root for later separation

### 6. Terminology blur

Current concern:
- terms such as Request, Scope, Plan, Task, WorkPackage, Job, Run, Session, and Artifact are not fully separated in the current repository language

Likely first-pass answer:
- do not bulk rename in Phase 0.3
- capture terminology ambiguity during inventory so later cleanup is guided, not improvised

Decision still needed:
- whether the ambiguity report should add a dedicated terminology section or whether a separate terminology note is preferred

## Immediate next actions

1. instantiate `repository-inventory.md` from the template
2. instantiate `migration-map.md` from the template
3. instantiate `ambiguity-report.md` from the template using the ambiguity list above as the seed
4. instantiate `public-import-surface.md` from the template
5. use those outputs to close the remaining freeze decisions in `PKT-FND-011`

## Proposed status of this document

Use this as a **seeded working view** for `PKT-FND-010`.
It should not replace the formal inventory, migration map, ambiguity report, or public-import-surface artifacts.
