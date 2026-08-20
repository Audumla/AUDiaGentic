# AUDiaGentic Rust baseline architecture

This spike locks the minimum architecture needed to build later applications without turning AUDiaGentic into a monolithic framework.

## Architectural vocabulary

Only four AUDiaGentic terms are required at the architecture level:

- **Runtime** — constructs and runs an application.
- **Application** — selects and connects components.
- **Component** — an implementation/building block, native Rust or WebAssembly Component.
- **Capability** — the semantic contract a component consumes or provides.

Normal ecosystem terms remain normal ecosystem terms: Rust crate, WIT interface, Wasm component, Bevy Plugin, MCP transport, Cargo dependency, artifact, configuration.

## Dependency bands

```text
applications
    |
adapters / concrete components
    |
capability APIs
    |
optional foundation libraries
    |
kernel
```

A dependency may point inward. Kernel and foundation crates must never acquire dependencies on optional application runtimes or protocol adapters.

## Locked kernel

### `kernel-core`

Owns only stable identity and execution context data:

- `ApplicationId`
- `ComponentId`
- `CapabilityId`
- `CorrelationId`
- `ApplicationContext`

It is deliberately not a service locator and has no runtime framework dependencies.

### `kernel-manifest`

Owns declarative application selection:

- application identity;
- component identity + artifact/source;
- per-component configuration;
- explicit capability-to-component bindings.

The manifest does **not** redeclare component imports or exports. Those contracts come from WIT/component inspection.

### `kernel-composition`

Validates explicit bindings against discovered component imports/exports. Missing, invalid, and duplicate bindings fail. It does not select an implicit winner.

### `application`

The current spike application object remains a deliberately small typed composition seam. It is not a registry, DI container, or generic `get<T>()` service locator.

## Optional foundation libraries

These are reusable implementation libraries, not mandatory runtime services.

### `foundation-diagnostics`

Machine code, severity, human message and optional help are distinct. Capability-specific typed errors remain owned by their capability.

### `foundation-sensitive`

Provides structurally protected `Secret<T>` values and conservative redaction helpers. Redaction is for diagnostic/output boundaries; legitimate persistence paths must retain the real value.

### `foundation-template`

Strict, pure string substitution. Domain-specific expression/value semantics remain in the domain capability.

### `foundation-reconcile`

Provides desired/observed ownership-aware planning and effect receipts. It is intentionally independent of files, JSON, recipes, and managed configuration.

### `foundation-config`

Provides ordered config layering, provenance and typed deserialization. It deliberately does not decide YAML/TOML/JSON file policy.

### `foundation-file-store`

Provides trusted native atomic file persistence and distinguishes absence from other I/O failure. It is implementation machinery, not the public filesystem capability.

## First capability/component layering proof

### `filesystem-api`

Defines the filesystem capability contract and a validated relative-path value. Consumers receive a scoped filesystem abstraction rather than ambient host paths.

### `filesystem-native`

Implements that contract using a capability-rooted `cap_std::fs::Dir`. Ambient authority is used once when the host opens the granted root; operations after that are relative to the granted directory. Tests cover ordinary read/write/remove behavior and denial of a symlink escape.

This distinction is deliberate:

```text
foundation-file-store
    trusted internal persistence helper

filesystem-api
    public semantic capability
        ^
        |
filesystem-native
    privileged native implementation
```

A future Wasm implementation can satisfy the same semantic capability through WASI/WIT without changing consumers.

## Optional implementations and adapters

- `runtime-bevy`: optional state-heavy capability implementation. No Bevy type crosses capability boundaries.
- `component-host`: current integration facade over the independently validated WIT/Wasm runtime spike; same-process embedding remains the next runtime gate.
- `mcp-adapter`: projects application capabilities through RMCP; MCP does not own application semantics.

## Non-negotiable boundary tests

CI must fail if kernel, application, foundation, or capability API crates pull in Bevy, RMCP, Wasmtime, or wash-runtime. Native capability implementations may depend on ordinary implementation libraries such as Tokio or `cap-std`, but not on unrelated optional application runtimes/adapters.

The baseline must not introduce:

- a plugin manager;
- generic service registry;
- service locator;
- dependency-injection container;
- process-global mutable application context;
- Bevy types in public capability APIs;
- MCP types in application/capability APIs;
- duplicated WIT import/export declarations in the application manifest.

## Next layer

The next production-oriented layer may add concrete host/capability implementations (process, secrets, observability, managed configuration, workflow, recipes, agents) by consuming these contracts and foundation libraries. Those additions do not widen the kernel unless a requirement is proven universal to arbitrary applications.
