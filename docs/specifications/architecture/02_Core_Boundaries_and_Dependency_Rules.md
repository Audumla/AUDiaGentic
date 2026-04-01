# Core Boundaries and Dependency Rules

## Mandatory dependency rules

### Core subsystems
- `core-lifecycle`
- `release-audit-ledger`
- `agent-jobs`
- `provider-layer`

### Optional subsystems
- `discord-overlay`
- `optional-server`

### Optional extension subsystems
- `nodes`
- `discovery`
- `federation`
- `connectors`

Historical docs may still mention the older `eventing` / `coordinator` / `connectivity`
split. The canonical extension taxonomy is now `nodes`, `discovery`, `federation`, and
`connectors`; later docs should use those names even when describing the same future seams.

## Allowed dependencies

```mermaid
flowchart LR
    L[core-lifecycle] --> R[release-audit-ledger]
    L --> J[agent-jobs]
    R --> J
    J --> P[provider-layer]
    R --> P
    J --> D[discord-overlay]
    R --> D
    L --> D
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

- `release-audit-ledger` must not depend on `discord-overlay`
- `agent-jobs` must not depend on `discord-overlay`
- `release-audit-ledger` must not require local AI
- `agent-jobs` must not require Discord for correctness
- `optional-server` must not become required for in-process execution
- `nodes`, `discovery`, `federation`, and `connectors` must remain optional extension layers and must not become required for single-node correctness, release correctness, or prompt-launch correctness
- `discovery` must not become a prerequisite for node-local operation
- `federation` must not become a prerequisite for node-local operation
- `connectors` must not become a prerequisite for node-local operation

## Implication for implementation

Every cross-module interaction must go through a documented contract, schema, or script boundary.
The later node/discovery/federation/connector layers are additive optional extension subsystems, not replacements for the baseline `core-lifecycle`, `release-audit-ledger`, `agent-jobs`, or `provider-layer` contracts.
