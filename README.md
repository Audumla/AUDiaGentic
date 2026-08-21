# AUDiaGentic

AUDiaGentic is a Rust platform for composing agentic applications and execution capabilities without turning the platform into a universal runtime or service container.

The repository is currently locked through the **Application Capabilities** layer. The working tree contains only the active Rust product line; superseded implementations remain available through Git history rather than living beside current code.

## Current layers

- `crates/audiagentic-core` — generic identity, execution/correlation identity, lifecycle, diagnostics, and opaque `Application<C>` composition.
- foundation crates — stable coded-error vocabulary, sensitive values, templates, deterministic reconciliation, typed configuration resolution/provenance, and low-level file storage.
- `crates/audiagentic-host` — narrow effect contracts and explicit authorities.
- `crates/audiagentic-host-native` — native filesystem and direct-child process implementations.
- application capabilities — typed domain events, deterministic workflow, deterministic time, and managed configuration.
- `examples/` — tiny/medium/large independence proofs plus the integrated application-capabilities proof.

## Architecture principles

- Core remains capability-neutral and zero-dependency.
- Raw configuration stops at application composition and becomes typed policy.
- Policy controls behaviour; authority controls permitted effects.
- External effects cross narrow host contracts.
- Public/reusable boundary failures have stable managed error identity while domain errors remain locally typed.
- Operational observability uses structured `tracing`; domain events are not telemetry.
- No global registry, service locator, generic plugin framework, event bus, scheduler, artifact system, or workflow manager is introduced without a proven requirement.
- Provider- and harness-native state remains provider-private; outer adapters do not become competing execution authorities.

The normative contracts are in:

- `docs/architecture/rust-production-foundation.md`
- `docs/architecture/application-capabilities.md`

## Build and validate

Rust is pinned by `rust-toolchain.toml`.

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
bash scripts/rust-foundation-smoke.sh
```

The GitHub `rust-production-foundation` workflow runs the architecture gate on Ubuntu, macOS, and Windows.
