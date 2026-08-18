# AUDiaGentic Rust + WebAssembly Component Model smoke

Greenfield foundation spike using Rust, WebAssembly Components, WIT and wasmCloud `wash-runtime`.

Pinned runtime source:

- wasmCloud commit: `998d4a75598a5269af07be2c21682f334f642eaa`
- workspace version at that commit: `2.7.0`
- Rust: `1.94.0`
- Wasmtime: `47.0.3`

## Requirements

- Rust 1.94.0
- `wasm32-wasip2` target
- `protoc` (`protobuf-compiler`) for building the pinned `wash-runtime` dependency
- Network/Git access for Cargo dependencies, including the pinned wasmCloud revision

## Run

```bash
rustup target add wasm32-wasip2 --toolchain 1.94.0
./scripts/smoke.sh
```

The smoke script builds all guest components directly with Cargo for `wasm32-wasip2`, then builds and runs the native Rust host. `wash-runtime` is embedded as a pinned Rust dependency; the `wash` CLI is not required.

Expected terminal marker:

```text
DEFAULT_PROVIDER=workflow-default:smoke
ALTERNATE_PROVIDER=workflow-alt:smoke
MISSING_PROVIDER_REJECTED=...
DUPLICATE_PROVIDER_REJECTED=...
AUDIT_CALLS=2
SMOKE_OK
```

See `ARCHITECTURE.md` for what this experiment is intended to prove.
