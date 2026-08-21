# AUDiaGentic

AUDiaGentic is a Rust platform for composing agentic applications and execution capabilities without turning the platform into a universal runtime or service container.

The repository is currently locked through the **Application Capabilities** layer. The working tree contains only the active Rust product line; superseded implementations remain available through Git history rather than living beside current code.

## Current layers

- `crates/audiagentic-core` — application/execution identity and opaque `Application<C>` composition only.
- pure foundation — stable coded-error vocabulary, sensitive values, deterministic templates/reconciliation, and typed configuration resolution/provenance.
- `crates/audiagentic-host` — proven filesystem/process contracts and explicit authorities; no native effects.
- `crates/audiagentic-host-native` — native filesystem durability/authority enforcement and direct-child process implementation.
- application capabilities — typed domain events, deterministic workflow, deterministic time, and managed configuration.
- `examples/` — tiny/medium/large independence proofs plus the integrated application-capabilities proof and application-edge structured tracing test.

There is no standalone storage/file-store layer. Durable filesystem mechanics are private to the native host implementation until a real cross-host storage abstraction proves a distinct contract.

## Architecture principles

- Core remains capability-neutral and zero-dependency; speculative lifecycle/diagnostic/component/capability abstractions do not live there.
- Pure foundation and reusable semantic capabilities are deterministic and native-effect-free.
- Raw configuration stops at application composition, retains revision/layer provenance, and becomes narrow typed policy.
- Policy controls behaviour; authority controls permitted effects.
- Only proven external effects receive host contracts. New network/secret/etc. contracts wait for a real consumer.
- Reusable boundary failures retain local typed errors while exposing stable managed code, category, canonical message, and resolution.
- Monotonic event/workflow identities fail explicitly on exhaustion; they do not panic or wrap.
- Operational observability uses structured `tracing` at the application/runtime edge; semantic libraries remain telemetry-backend-free and domain events are not telemetry.
- No global registry, service locator, generic plugin framework, event bus, scheduler, artifact system, workflow manager, or observability manager is introduced without a proven requirement.
- Provider- and harness-native state remains provider-private; outer adapters do not become competing execution authorities.

The normative contracts are:

- `docs/architecture/rust-production-foundation.md`
- `docs/architecture/application-capabilities.md`

## Build and validate

Rust is pinned by `rust-toolchain.toml` and the dependency graph is committed in `Cargo.lock`.

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
bash scripts/rust-foundation-smoke.sh
```

The GitHub `rust-production-foundation` workflow runs the same layer contract on Ubuntu, macOS, and Windows.
