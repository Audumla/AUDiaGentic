# Module Ownership and Parallelization Map

## Ownership groups

| Group | Owns | May edit directly | Must not edit directly |
|---|---|---|---|
| Contracts | `src/audiagentic/contracts/*`, `docs/schemas/*`, glossary, canonical ids | contracts, validators, fixtures | lifecycle, release, jobs, providers |
| Lifecycle | `src/audiagentic/lifecycle/*`, lifecycle CLI behavior | lifecycle modules, lifecycle tests | release core internals, jobs internals |
| Release | `src/audiagentic/release/*`, tracked release docs behavior | release modules, release tests, release fixtures | lifecycle detection, jobs state machine |
| Jobs | `src/audiagentic/jobs/*` | job modules/tests | release file formats, lifecycle manifests |
| Providers | `src/audiagentic/providers/*` | provider modules/tests | release core, lifecycle core |
| Discord | `src/audiagentic/overlay/discord/*` | discord modules/tests | core state shapes |
| Server | `src/audiagentic/server/*` | service seam only | any contract fields |
| Nodes | `src/audiagentic/nodes/*` | node identity, heartbeat, status, ownership | lifecycle, release, provider core |
| Discovery | `src/audiagentic/discovery/*` | locator provider contracts and static registry | core node contracts, release core |
| Eventing | `src/audiagentic/eventing/*` | node events and control request contracts | node identity, discovery, core release |
| Connectors | `src/audiagentic/connectors/*` | external task-system connectors | core execution truth, release core |

## Parallel work rules

- Two packets may run in parallel only if they do not share primary ownership.
- Any packet touching `docs/schemas/*` or `03_Common_Contracts.md` blocks parallel packets touching contracts.
- Any packet touching tracked files under `docs/releases/` must coordinate through the release owner.
- Provider adapter packets can run in parallel after `PKT-PRV-001` and `PKT-PRV-002` are merged.
- Discord packets can run in parallel with migration hardening once events and approvals are frozen.
- Node packets can run in parallel after the Phase 4 provider/runtime stabilization checkpoint and the node contract packet is frozen.
- Discovery packets can run in parallel after the node identity packet is frozen.
- Eventing packets can run in parallel after node identity and discovery packets are frozen.
- Coordinator and connector packets should wait until the node/discovery/eventing seams are frozen.


## Extension ownership note

Phase 3.2 prompt launch and review implementation remains in the **Jobs** ownership group even when adapters are triggered from CLI or VS Code. CLI or editor surfaces must remain thin normalization adapters and must not duplicate job orchestration logic.
