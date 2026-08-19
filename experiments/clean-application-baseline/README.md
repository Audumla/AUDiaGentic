# Clean application baseline spike

Decision spike for the minimal AUDiaGentic vocabulary and multi-repo-friendly application model.

Architectural terms under test:

- Runtime
- Application
- Component
- Capability

The spike must prove that a small application can use plain Rust capabilities without Bevy, a larger application can use a Bevy-backed component privately, a runtime-loaded WebAssembly Component can satisfy a WIT capability, and the same application capability can be projected through MCP without protocol/runtime types leaking across boundaries.

This is an architecture experiment only. Do not merge as production architecture.
