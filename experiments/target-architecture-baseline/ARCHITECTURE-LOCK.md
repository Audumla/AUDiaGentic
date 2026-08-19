# Architecture lock — baseline 1

The following invariants are treated as locked by this spike unless a later proof falsifies them.

1. The generic architecture vocabulary is Runtime, Application, Component, Capability.
2. `Application<S>` never becomes a service locator or type-indexed capability registry.
3. Native capability composition is strongly typed Rust composition.
4. Cross-component capability contracts use WIT when they cross the WebAssembly boundary.
5. Infrastructure libraries may be used directly behind capability boundaries; AUDiaGentic does not wrap APIs merely to rename them.
6. Bevy is an optional implementation technology and no Bevy type crosses a capability API.
7. MCP and other protocols are adapters/projections, not application foundations.
8. Configuration semantics are separate from managed external configuration semantics.
9. Redaction happens at diagnostic/output boundaries; legitimate persistence does not silently redact stored values.
10. Reconciliation owns desired/observed/ownership semantics; filesystem/process effects stay outside it.
11. Stable managed identity is separate from a mutable target name; ownership evidence is separate from user-owned target data.
12. Capability-specific errors and schemas live with the capability. Core contains only universal diagnostic primitives.
13. Artifact resolution produces immutable digest/lock evidence; resolution transport is not part of the application model.
14. Runtime preparation validates generic manifest invariants and immutable artifact evidence, then delegates typed state construction to the concrete application.
15. Heavy runtime dependencies must remain absent from `audiagentic-core`, `audiagentic-application`, and generic `audiagentic-runtime`.
16. Generated Wasm ABI glue may contain generated unsafe code; handwritten baseline/core/capability code remains `forbid(unsafe_code)` where practical.
