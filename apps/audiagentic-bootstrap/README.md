# AUDiaGentic Rust bootstrap

This package is the first concrete application-owned composition built on AudiaCore Stage 9.

It proves the runtime boundary:

```text
Cargo metadata resolves AudiaCore at an exact revision
        -> bootstrap constructs concrete typed collaborators
        -> Application<AudiagenticComposition>
        -> normal runtime code has no source/package lookup
```

Current composition:

- `BootstrapState`: `NativeFileHost`, explicit read/write authorities, and a Managed Content target;
- `EventStream<BootstrapEvent>`: caller-owned mutable application activity state.

The executable applies desired content, verifies it, applies the same desired content again, and requires `Created` then `Noop` while recording both operations in the event stream.

This package does **not** introduce a component registry, service locator, dependency container, plugin manager, generic lifecycle trait, package installer, or runtime loader. Source selection belongs in `Cargo.toml`/`Cargo.lock`; application source receives typed Rust APIs only.

Validation is owned by `.github/workflows/ci-rust-bootstrap.yml`: exact AudiaCore revision check, source-location leakage check, rustfmt, Clippy with warnings denied, locked tests, and locked execution on Ubuntu, macOS, and Windows.

The architectural progression and Stage 9 lock decisions are preserved in AudiaCore `docs/architecture/stage9-application-assembly.md`.
