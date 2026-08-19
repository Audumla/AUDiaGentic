#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/../.." && pwd)"

cd "$ROOT"
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace

assert_tree_excludes() {
  local package="$1"
  local pattern="$2"
  local tree
  tree="$(cargo tree -p "$package")"
  echo "$tree"
  if printf '%s\n' "$tree" | grep -Eiq "$pattern"; then
    echo "$package leaked forbidden infrastructure dependency: $pattern" >&2
    exit 1
  fi
}

assert_tree_excludes audiagentic-core-spike 'bevy|rmcp|wasmtime|wash-runtime|tokio'
assert_tree_excludes audiagentic-application-spike 'bevy|rmcp|wasmtime|wash-runtime'
assert_tree_excludes audiagentic-sensitive-spike 'bevy|rmcp|wasmtime|wash-runtime|tokio'
assert_tree_excludes audiagentic-template-spike 'bevy|rmcp|wasmtime|wash-runtime|tokio'
assert_tree_excludes audiagentic-reconcile-spike 'bevy|rmcp|wasmtime|wash-runtime|tokio'
assert_tree_excludes audiagentic-config-spike 'bevy|rmcp|wasmtime|wash-runtime|tokio'
echo "ARCHITECTURE_DEPENDENCIES_OK"

"$REPO_ROOT/experiments/rust-wasm-foundation/scripts/smoke.sh"
WASM_BIN="$REPO_ROOT/experiments/rust-wasm-foundation/host/target/release/audiagentic-rust-wasm-smoke"
test -x "$WASM_BIN"

AUDIAGENTIC_WASM_SMOKE_BIN="$WASM_BIN" cargo run -p audiagentic-clean-baseline-smoke --release

echo "RUST_BASELINE_V2_SMOKE_OK"
