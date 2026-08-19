#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/../.." && pwd)"

cd "$ROOT"
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace

TREE="$(cargo tree -p audiagentic-application-spike)"
echo "$TREE"
if printf '%s\n' "$TREE" | grep -Eiq 'bevy|rmcp|wasmtime|wash-runtime'; then
  echo "application crate leaked infrastructure dependency" >&2
  exit 1
fi
echo "MINIMAL_DEPENDENCIES_OK"

"$REPO_ROOT/experiments/rust-wasm-foundation/scripts/smoke.sh"
WASM_BIN="$REPO_ROOT/experiments/rust-wasm-foundation/host/target/release/audiagentic-rust-wasm-smoke"
test -x "$WASM_BIN"

AUDIAGENTIC_WASM_SMOKE_BIN="$WASM_BIN" cargo run -p audiagentic-clean-baseline-smoke --release

echo "CLEAN_APPLICATION_BASELINE_SMOKE_OK"
