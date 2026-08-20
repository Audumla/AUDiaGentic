#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked

cargo run --locked --quiet -p audiagentic-example-tiny
cargo run --locked --quiet -p audiagentic-example-medium
cargo run --locked --quiet -p audiagentic-example-large

core_tree="$(cargo tree --locked -p audiagentic-core --edges normal --prefix none)"
core_lines="$(printf '%s\n' "$core_tree" | sed '/^[[:space:]]*$/d' | wc -l)"
if [[ "$core_lines" -ne 1 ]]; then
    echo "CORE_DEPENDENCY_LEAK: audiagentic-core must have zero normal dependencies" >&2
    printf '%s\n' "$core_tree" >&2
    exit 1
fi

tiny_tree="$(cargo tree --locked -p audiagentic-example-tiny --edges normal --prefix none)"
for forbidden in bevy rmcp wasmtime wash-runtime tokio async-trait; do
    if printf '%s\n' "$tiny_tree" | grep -Fq "$forbidden"; then
        echo "TINY_APP_LAYER_LEAK: found $forbidden" >&2
        exit 1
    fi
done

host_tree="$(cargo tree --locked -p audiagentic-host --edges normal --prefix none)"
for forbidden in audiagentic-config audiagentic-file-store audiagentic-template audiagentic-reconcile; do
    if printf '%s\n' "$host_tree" | grep -Fq "$forbidden"; then
        echo "HOST_LAYER_LEAK: found $forbidden" >&2
        exit 1
    fi
done

if grep -R --include='*.rs' -E '\b(Workflow|ComponentProbe|DynApplication)\b' crates/audiagentic-core >/dev/null; then
    echo "CORE_DOMAIN_LEAK: spike-specific capability vocabulary entered audiagentic-core" >&2
    exit 1
fi

if grep -R --include='Cargo.toml' -E '\b(bevy|rmcp|wasmtime|wash-runtime|tokio|async-trait)\b' crates examples >/dev/null; then
    echo "FOUNDATION_RUNTIME_LEAK: runtime/transport dependency entered the production foundation" >&2
    exit 1
fi

echo "CORE_LAYER_OK"
echo "FOUNDATION_LIBRARIES_OK"
echo "HOST_BOUNDARY_OK"
echo "TINY_MEDIUM_LARGE_OK"
echo "RUST_PRODUCTION_FOUNDATION_OK"
