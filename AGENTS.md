# Repository instructions

AUDiaGentic is being rebuilt as a Rust platform. The working tree is the current product line; do not reintroduce the retired Python/Node implementation, generated provider instruction copies, local MCP configuration, archived source, or compatibility scaffolding.

## Architecture

Keep the dependency direction explicit:

`core -> foundation semantics -> host contracts -> native hosts -> application capabilities -> application/adapter edges`

`audiagentic-core` stays capability-neutral and dependency-free. It owns only proven application/execution identity and opaque `Application<C>` composition. Lifecycle, diagnostics, component/capability registries, and other taxonomy do not enter core until a real higher-layer consumer proves them.

Foundation and capability crates stay small and semantic. Do not add service locators, global registries, DI containers, generic provider/plugin frameworks, event buses, workflow managers, schedulers, artifact systems, or other platform-wide managers without a proven consumer and boundary.

## Locked rules

- Raw configuration stops at application composition. Semantic capabilities consume application-owned typed values or capability-owned policy; they do not read files or environment variables.
- Resolved configuration retains source-layer identity and a deterministic configuration revision for provenance.
- Policy decides behaviour. Authority determines which external effects are permitted.
- Proven filesystem and process effects cross narrow host contracts. Add network, secret, or other host facilities only when a real consumer proves the required semantics.
- Capability/domain errors remain typed Rust errors. Errors crossing a reusable boundary expose stable canonical codes, machine categories, messages, and resolutions through `audiagentic-errors`.
- One stable error code represents one semantic condition. Dynamic context belongs in typed error data, not in the canonical message.
- Operational observability uses structured Rust `tracing` at application/runtime/effect boundaries. Libraries never install or own a tracing subscriber. Domain events are not telemetry.
- Sensitive values must not enter error messages, tracing fields, or safe metadata.
- Domain events, execution output, errors, and operational telemetry are distinct concepts.
- Pure semantic logic remains deterministic and I/O-free unless the crate is explicitly an effect implementation.
- Do not preserve obsolete implementation files in-tree for reference; Git history is the reference.

## Validation

For substantive Rust changes run the production foundation gate:

```bash
bash scripts/rust-foundation-smoke.sh
```

The gate includes formatting, strict Clippy, workspace tests, executable composition proofs, dependency-direction checks, stable-error checks, configuration/policy checks, observability rules, and effect-boundary checks. The GitHub workflow validates the same contract on Linux, macOS, and Windows.
