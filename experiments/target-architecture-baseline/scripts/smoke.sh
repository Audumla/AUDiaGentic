#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace

for package in \
  audiagentic-core \
  audiagentic-application \
  audiagentic-config \
  audiagentic-template \
  audiagentic-reconcile; do
  tree="$(cargo tree -p "$package")"
  printf '%s\n' "$tree"
  if printf '%s\n' "$tree" | grep -Eiq 'bevy|rmcp|wasmtime|wash-runtime|tokio'; then
    echo "$package leaked a heavyweight runtime dependency" >&2
    exit 1
  fi
done

echo "FOUNDATION_DEPENDENCIES_OK"
cargo run -p target-baseline-demo --quiet

echo "TARGET_ARCHITECTURE_BASELINE_OK"
