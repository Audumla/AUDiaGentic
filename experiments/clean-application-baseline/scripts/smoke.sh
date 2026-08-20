#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/../.." && pwd)"

cd "$ROOT"
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace

assert_clean_tree() {
  local package="$1"
  local label="$2"
  local tree
  tree="$(cargo tree -p "$package")"
  echo "--- $label dependency tree ---"
  echo "$tree"
  if printf '%s\n' "$tree" | grep -Eiq 'bevy|rmcp|wasmtime|wash-runtime'; then
    echo "$label leaked optional runtime/adapter dependency" >&2
    exit 1
  fi
}

assert_clean_tree audiagentic-kernel-core-spike KERNEL_CORE
assert_clean_tree audiagentic-kernel-manifest-spike KERNEL_MANIFEST
assert_clean_tree audiagentic-kernel-composition-spike KERNEL_COMPOSITION
assert_clean_tree audiagentic-application-spike APPLICATION
assert_clean_tree audiagentic-foundation-diagnostics-spike FOUNDATION_DIAGNOSTICS
assert_clean_tree audiagentic-foundation-sensitive-spike FOUNDATION_SENSITIVE
assert_clean_tree audiagentic-foundation-template-spike FOUNDATION_TEMPLATE
assert_clean_tree audiagentic-foundation-reconcile-spike FOUNDATION_RECONCILE
assert_clean_tree audiagentic-foundation-config-spike FOUNDATION_CONFIG
assert_clean_tree audiagentic-foundation-file-store-spike FOUNDATION_FILE_STORE
assert_clean_tree audiagentic-workflow-api-spike WORKFLOW_API
assert_clean_tree audiagentic-component-probe-api-spike COMPONENT_PROBE_API
assert_clean_tree audiagentic-filesystem-api-spike FILESYSTEM_API
assert_clean_tree audiagentic-filesystem-native-spike FILESYSTEM_NATIVE
assert_clean_tree audiagentic-process-api-spike PROCESS_API
assert_clean_tree audiagentic-process-native-spike PROCESS_NATIVE
assert_clean_tree audiagentic-managed-config-api-spike MANAGED_CONFIG_API
assert_clean_tree audiagentic-managed-config-json-spike MANAGED_CONFIG_JSON

echo "BASELINE_DEPENDENCY_BOUNDARIES_OK"

"$REPO_ROOT/experiments/rust-wasm-foundation/scripts/smoke.sh"
WASM_BIN="$REPO_ROOT/experiments/rust-wasm-foundation/host/target/release/audiagentic-rust-wasm-smoke"
test -x "$WASM_BIN"

AUDIAGENTIC_WASM_SMOKE_BIN="$WASM_BIN" cargo run -p audiagentic-clean-baseline-smoke --release

echo "RUST_BASELINE_FOUNDATION_SMOKE_OK"
