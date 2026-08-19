# AUDiaGentic target architecture baseline

This is the first fuller baseline built on top of the clean application composition spike.
It intentionally locks only the architecture that should survive across small and large applications.

## Locked vocabulary

- **Runtime** — constructs and runs an application.
- **Application** — immutable identity/context plus application-defined typed state.
- **Component** — an implementation building block selected by an application.
- **Capability** — the contract between consumers and implementations.

No generic AUDiaGentic plugin/provider/service-registry vocabulary is introduced.

## Locked dependency rule

```text
application / adapters / capability implementations
                    |
                    v
              foundation libs
                    |
                    v
                  core
```

`audiagentic-application` is deliberately generic as `Application<S>`. It does not contain a
capability registry, service locator, workflow slot, MCP knowledge, Bevy types, or Wasm runtime types.
Each real application defines its own strongly typed state/capability handles.

## Baseline crates

- `audiagentic-core` — canonical IDs, application/component manifest data, diagnostics, immutable application context.
- `audiagentic-application` — `Application<S>` only.
- `audiagentic-config` — ordered config layers, deterministic deep merge, typed deserialization, leaf provenance.
- `audiagentic-sensitive` — secret wrapper re-exports plus deterministic output/key redaction helpers.
- `audiagentic-template` — strict, pure dotted-path `{path.to.value}` rendering over JSON-like data.
- `audiagentic-reconcile` — generic desired/observed ownership planning and effect receipt data.

The `examples/` crates prove a capability contract can live outside the base and be assembled into a
typed application without changing `Application<S>`.

## Explicitly not core

The following remain optional layers and must not leak into `core` or `application`:

- Bevy / ECS runtime implementations;
- MCP, CLI, HTTP, ACP, A2A and other edge adapters;
- Wasmtime / wash-runtime component hosting;
- filesystem, process, network and secret authority;
- workflow, recipes, agents, managed config and managed process semantics;
- tracing/OpenTelemetry exporters;
- database/provider SDKs.

## Next layer after this baseline

1. embedded component host behind WIT capability boundaries;
2. host authority crates for filesystem/process/secrets/config/observability;
3. managed-config built from `reconcile` + host filesystem rather than placed in core;
4. application artifact resolution and immutable resolved-manifest/lock data;
5. adapters such as MCP consuming explicit capability handles;
6. optional Bevy-backed capability runtimes.

This remains a decision spike. Promotion into production crates should preserve the locked invariants
rather than copy directory structure blindly.
