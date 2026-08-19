#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cargo fmt --all -- --check
cargo fmt --manifest-path components/greeting/Cargo.toml -- --check
cargo fmt --manifest-path examples/external-app/Cargo.toml -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo clippy --manifest-path examples/external-app/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path examples/external-app/Cargo.toml

for package in \
  audiagentic-core \
  audiagentic-application \
  audiagentic-artifact \
  audiagentic-runtime \
  audiagentic-config \
  audiagentic-template \
  audiagentic-reconcile \
  audiagentic-file-store \
  audiagentic-managed-config; do
  tree="$(cargo tree -p "$package")"
  printf '%s\n' "$tree"
  if printf '%s\n' "$tree" | grep -Eiq 'bevy|rmcp|wasmtime|wash-runtime|tokio'; then
    echo "$package leaked a heavyweight runtime dependency" >&2
    exit 1
  fi
done

EXTERNAL_TREE="$(cargo tree --manifest-path examples/external-app/Cargo.toml)"
if printf '%s\n' "$EXTERNAL_TREE" | grep -Eiq 'bevy|rmcp|wasmtime|wash-runtime|tokio'; then
  echo "standalone consumer unexpectedly pulled a heavyweight runtime dependency" >&2
  exit 1
fi
echo "EXTERNAL_APP_DEPENDENCIES_OK"

echo "FOUNDATION_DEPENDENCIES_OK"
cargo run -p target-baseline-demo --quiet
cargo run --manifest-path examples/external-app/Cargo.toml --quiet

cargo build --manifest-path components/greeting/Cargo.toml --target wasm32-wasip2 --release
COMPONENT="$ROOT/components/greeting/target/wasm32-wasip2/release/target_baseline_greeting_component.wasm"
test -f "$COMPONENT"

WASM_TREE="$(cargo tree -p target-baseline-wasm-demo)"
if printf '%s\n' "$WASM_TREE" | grep -Eiq 'wash-runtime|async-nats|redis'; then
  echo "direct Wasmtime adapter unexpectedly pulled wash-runtime/distributed infrastructure" >&2
  exit 1
fi
WASM_DEP_LINES="$(printf '%s\n' "$WASM_TREE" | sed 's/^[^A-Za-z0-9]*//' | sort -u | wc -l | tr -d ' ')"
echo "DIRECT_WASMTIME_DEP_LINES=$WASM_DEP_LINES"

cargo build -p target-baseline-wasm-demo --release
WASM_HOST_BIN="$ROOT/target/release/target-baseline-wasm-demo"
WASM_HOST_SIZE="$(stat -c%s "$WASM_HOST_BIN")"
echo "DIRECT_WASMTIME_HOST_BYTES=$WASM_HOST_SIZE"
"$WASM_HOST_BIN" "$COMPONENT"

echo "TARGET_ARCHITECTURE_BASELINE_OK"
