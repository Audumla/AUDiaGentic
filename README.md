# AUDiaGentic

AUDiaGentic is a Rust platform for composing agentic applications and execution capabilities without turning the platform into a universal runtime or service container.

The repository is currently locked through the **Application Capabilities** layer. The working tree contains only the active Rust product line; superseded implementations remain available through Git history rather than living beside current code.

## Current layers

- `crates/audiagentic-core` — proven application/execution identity and opaque `Application<C>` composition only.
- foundation crates — stable coded-error vocabulary, sensitive values, templates, deterministic reconciliation, typed configuration resolution/provenance, and low-level file storage.
- `crates/audiagentic-host` — proven filesystem/process contracts and explicit authorities.
- `crates/audiagentic-host-native` — native filesystem and direct-child process implementations.
- application capabilities — typed domain events, deterministic workflow, deterministic time, and managed configuration.
- `examples/` — tiny/medium/large independence proofs plus the integrated application-capabilities proof and application-edge structured tracing test.

## Architecture principles

- Core remains capability-neutral and zero-dependency; unused lifecycle/diagnostic/component/capability abstractions do not live there speculatively.
- Raw configuration stops at application composition, retains revision/layer provenance, and becomes narrow typed policy.
- Policy controls behaviour; authority controls permitted effects.
- Only proven external effects receive host contracts. New network/secret/etc. contracts wait for a real consumer.
- Public/reusable boundary failures retain local typed errors while exposing stable managed code, category, canonical message, and resolution.
- Operational observability uses structured `tracing` at the application/runtime edge; semantic libraries remain telemetry-backend-free and domain events are not telemetry.
- No global registry, service locator, generic plugin framework, event bus, scheduler, artifact system, or workflow manager is introduced without a proven requirement.
- Provider- and harness-native state remains provider-private; outer adapters do not become competing execution authorities.

The normative contracts are in:

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

The GitHub `rust-production-foundation` workflow runs the same architecture gate on Ubuntu, macOS, and Windows.
