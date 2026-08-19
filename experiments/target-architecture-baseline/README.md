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
- `audiagentic-config` — thin ordered-precedence policy over Figment; Figment owns recursive merge, typed extraction and per-value provenance.
- `audiagentic-sensitive` — `secrecy` integration plus output/key/structural redaction helpers.
- `audiagentic-template` — pure strict dotted-path template rendering.
- `audiagentic-reconcile` — generic desired/observed ownership planning + receipts.
- `audiagentic-file-store` — small native persistence helper using `atomic-write-file`; missing and malformed data remain distinct.

The `examples/` crates prove a capability contract can live outside the base and be assembled into a
typed application without changing `Application<S>`. A second example implements that same capability
with a runtime-loaded WebAssembly Component using Wasmtime directly behind the capability boundary.

## Explicitly not core

The following remain optional layers and must not leak into `core` or `application`:

- Bevy / ECS runtime implementations;
- MCP, CLI, HTTP, ACP, A2A and other edge adapters;
- Wasmtime / wash-runtime component hosting implementations;
- filesystem, process, network and secret authority;
- workflow, recipes, agents, managed config and managed process semantics;
- tracing/OpenTelemetry exporters;
- database/provider SDKs.

## Next layer after this baseline

1. host authority crates/interfaces for filesystem/process/secrets/config/observability;
2. managed-config built from `reconcile` + file-store + host filesystem rather than placed in core;
3. application artifact resolution and immutable resolved-manifest/lock data;
4. adapters such as MCP consuming explicit capability handles;
5. optional Bevy-backed capability runtimes.

This remains a decision spike. Promotion into production crates should preserve the locked invariants
rather than copy directory structure blindly.
