# Core Boundaries and Dependency Rules

## Mandatory dependency rules

### Core subsystems
- `core-lifecycle`
- `release-audit-ledger`
- `agent-jobs`
- `provider-layer`

### Optional subsystems
- `optional-server`

### Optional extension subsystems
- `nodes`
- `discovery`
- `federation`
- `connectors`

Historical docs may still mention the older `eventing` / `coordinator` / `connectivity`
split. The canonical extension taxonomy is now `nodes`, `discovery`, `federation`, and
`connectors`; later docs should use those names even when describing the same future seams.

## Repository-domain dependency rules for the Phase 0.3 refactor

The subsystem rules above remain the high-level architecture boundary. During the repository
domain refactor, the following repository-domain dependency rules are also canonical for code
placement and import repair inside `src/audiagentic/`.

### Repository domains

- `contracts`
- `core`
- `config`
- `scoping`
- `execution`
- `runtime`
- `channels`
- `streaming`
- `observability`
- reserved extension roots:
  - `nodes`
  - `discovery`
  - `federation`
  - `connectors`

### Allowed repository-domain dependencies

| Domain | May depend on |
|---|---|
| `contracts` | no repository-domain dependencies required |
| `core` | `contracts` |
| `config` | `contracts`, `core` |
| `scoping` | `contracts`, `core`, `config` |
| `execution` | `contracts`, `core`, `config`, selected `runtime` ports/records, selected `streaming` ports/adapters |
| `runtime` | `contracts`, `core`, `config` |
| `channels` | `contracts`, `core`, `config`, selected runtime-facing records, selected execution entrypoints/facades |
| `streaming` | `execution`, `runtime`, `channels`, `contracts`, `core` |
| `observability` | `runtime`, `contracts`, `core`, `config` |
| `nodes` | optional extension root; may depend on baseline contracts/core/config as later frozen |
| `discovery` | optional extension root; may depend on `nodes` contracts and baseline contracts/core/config as later frozen |
| `federation` | optional extension root; may depend on `nodes`, `discovery`, and baseline contracts/core/config as later frozen |
| `connectors` | optional extension root; may depend on `federation` and baseline contracts/core/config as later frozen |

### Forbidden repository-domain dependencies

- `scoping` must not depend on `channels`
- `scoping` must not depend on `observability`
- `execution` must not depend on channel formatting or rendering internals
- `runtime` must not depend on `channels`
- `channels` must not depend on execution orchestration internals beyond explicitly approved entrypoint/facade seams
- `observability` must not own or control live interaction/session steering
- `streaming` must not become the owner of durable observability storage policy
- reserved extension roots must not become required for baseline single-node correctness during the Phase 0.3 tranche

### Implication for the refactor checkpoint

- `03_Target_Codebase_Tree.md` and `05_Module_Ownership_and_Parallelization_Map.md` should be
  read together with this section when deciding destination modules during `PKT-FND-012`.
- When a moved module appears to need a forbidden dependency direction, stop the move and resolve
  the boundary in `PKT-FND-011` or a follow-on checkpoint packet rather than letting the code move
  redefine the dependency model implicitly.
- Reserved extension roots remain reserved roots during this tranche; they are not absorbed into the
  baseline repository-domain tree.

## Allowed dependencies

```mermaid
flowchart LR
    L[core-lifecycle] --> R[release-audit-ledger]
    L --> J[agent-jobs]
    R --> J
    J --> P[provider-layer]
    R --> P
    J --> S[optional-server]
    R --> S
    L --> S
    L --> N[nodes]
    R --> N
    J --> N
    N --> G[discovery]
    N --> F[federation]
    N --> C[connectors]
    G --> F
    F --> C
  ```

## Forbidden dependencies

- `release-audit-ledger` must not require local AI
- `agent-jobs` must not require any external messaging/control surface for correctness
- `optional-server` must not become required for in-process execution
- `nodes`, `discovery`, `federation`, and `connectors` must remain optional extension layers and must not become required for single-node correctness, release correctness, or prompt-launch correctness
- `discovery` must not become a prerequisite for node-local operation
- `federation` must not become a prerequisite for node-local operation
- `connectors` must not become a prerequisite for node-local operation

## Implication for implementation

Every cross-module interaction must go through a documented contract, schema, or script boundary.
The later node/discovery/federation/connector layers are additive optional extension subsystems, not replacements for the baseline `core-lifecycle`, `release-audit-ledger`, `agent-jobs`, or `provider-layer` contracts.
