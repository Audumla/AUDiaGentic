# Module Ownership and Parallelization Map

## Frozen ownership groups for the Phase 0.3 target shape

| Group | Owns | May edit directly | Must not edit directly |
|---|---|---|---|
| Contracts | `src/audiagentic/contracts/*`, `docs/schemas/*`, canonical ids, glossary, validation fixtures | contract modules, validators, fixtures | execution, runtime, channels, streaming, observability |
| CoreConfig | `src/audiagentic/core/*`, `src/audiagentic/config/*` | shared core helpers, config loaders, stable APIs | feature-specific execution/runtime/channel logic |
| Scoping | `src/audiagentic/scoping/*` | request/scope/plan shaping, scoping tests/docs | runtime internals, channel implementations |
| Execution | `src/audiagentic/execution/*` | jobs, provider execution, execution tests/docs | runtime persistence internals, channel formatting/rendering |
| Runtime | `src/audiagentic/runtime/*` | lifecycle, release, runtime state, runtime tests/docs | execution orchestration internals, channel rendering |
| Channels | `src/audiagentic/channels/*` | CLI, Discord, optional server-facing channel adapters | execution orchestration semantics, runtime persistence internals |
| Streaming | `src/audiagentic/streaming/*` | live input/output flow, stream bridges, stream capture helpers | telemetry storage, durable observability concerns |
| Observability | `src/audiagentic/observability/*` | diagnostics, telemetry/reporting, monitoring-oriented helpers | live interaction control or channel/session steering |
| Nodes | `src/audiagentic/nodes/*` | node identity, heartbeat, ownership, status | baseline lifecycle/release/provider core |
| Discovery | `src/audiagentic/discovery/*` | locator providers and registry resolution | baseline node contracts, release core |
| Federation | `src/audiagentic/federation/*` | node events, control transport, federation seams | baseline node identity/discovery ownership |
| Connectors | `src/audiagentic/connectors/*` | external task-system / tool connectivity | baseline execution truth, release core |

## Parallel work rules

- Two packets may run in parallel only if they do not share primary ownership.
- Any packet touching `docs/schemas/*` or `03_Common_Contracts.md` blocks parallel packets touching `Contracts`.
- Any packet touching tracked files under `docs/releases/` must coordinate through the `Runtime` owner while Phase 0.3 is active.
- `Execution` and `Channels` work may proceed in parallel only after the Phase 0.3 dependency rules are frozen and the affected interfaces are explicitly documented.
- `Streaming` and `Observability` must not be refactored in the same packet unless the packet explicitly freezes the interaction boundary between them first.
- `Nodes`, `Discovery`, `Federation`, and `Connectors` remain future extension ownership groups and should not be claimed as part of the baseline Phase 0.3 code move except to preserve their reserved paths.
- Discord overlay behavior is now treated as part of `Channels` for the repository-domain refactor tranche. Future Discord feature packets may still be tracked separately at the packet level, but they should not redefine channel ownership boundaries.

## Transitional compatibility note

Legacy ownership group names such as `Lifecycle`, `Release`, `Jobs`, `Providers`, `Server`, or `Discord` may still appear in older docs or shim paths during the checkpoint. They are no longer the canonical ownership model once `PKT-FND-011` is verified.

## Execution-boundary note

Phase 3.2 prompt launch and review implementation now belongs to the **Execution** ownership group even when surfaced through CLI, VS Code, Discord, or other channels. Channel adapters must remain thin normalization or interaction surfaces and must not duplicate execution semantics.
