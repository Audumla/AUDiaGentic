# AUDiaGentic target architecture baseline

This baseline is built on the clean application composition spike and locks only architecture that
should survive across small and large applications.

## Locked vocabulary

- **Runtime** — validates and prepares immutable application inputs, then delegates typed state construction.
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
- `audiagentic-artifact` — immutable artifact lock data plus resolver seam and strict local `file:` resolver/digest verifier.
- `audiagentic-runtime` — generic manifest validation + artifact preparation followed by app-owned typed state construction.
- `audiagentic-config` — thin ordered-precedence policy over Figment; Figment owns recursive merge, typed extraction and per-value provenance.
- `audiagentic-sensitive` — `secrecy` integration plus output/key/structural redaction helpers.
- `audiagentic-template` — pure strict dotted-path template rendering.
- `audiagentic-reconcile` — stable managed IDs, desired/observed planning, separate ownership evidence, collision protection and receipts.
- `audiagentic-file-store` — small native persistence helper using `atomic-write-file`; missing and malformed data remain distinct.

## Layer proofs

- `capabilities/managed-config` is a real capability above the foundation. It composes `reconcile` and `file-store` without entering core.
- `examples/wasm-app` implements an ordinary capability with a Wasm component using Wasmtime privately behind the capability boundary.
- `examples/external-app` is a standalone Cargo workspace excluded from the baseline workspace. It consumes the baseline crates through dependency paths as a stand-in for future registry/Git versions, owns its own application manifest and state, and proves no source-tree inheritance is required.

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

1. host authority interfaces for filesystem/process/secrets/config/observability, preferring WASI interfaces where they already fit;
2. OCI artifact resolution producing the same immutable lock data as the local resolver;
3. durable effect/journal semantics above `reconcile` for crash recovery across multiple effects;
4. adapters such as MCP consuming explicit capability handles;
5. optional Bevy-backed capability runtimes.

This remains a decision spike. Promotion into production crates should preserve the locked invariants
rather than copy directory structure blindly.
