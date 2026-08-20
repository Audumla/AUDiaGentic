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
cargo run --locked --quiet -p audiagentic-example-capabilities

core_tree="$(cargo tree --locked -p audiagentic-core --edges normal --prefix none)"
core_lines="$(printf '%s\n' "$core_tree" | sed '/^[[:space:]]*$/d' | wc -l)"
if [[ "$core_lines" -ne 1 ]]; then
    echo "CORE_DEPENDENCY_LEAK: audiagentic-core must have zero normal dependencies" >&2
    printf '%s\n' "$core_tree" >&2
    exit 1
fi

workspace_tree="$(cargo tree --workspace --locked --edges normal --prefix none)"
for forbidden in bevy rmcp wasmtime wash-runtime tokio async-trait; do
    if printf '%s\n' "$workspace_tree" | grep -E "^${forbidden}([[:space:]]|$)" >/dev/null; then
        echo "FOUNDATION_RUNTIME_LEAK: resolved workspace dependency includes $forbidden" >&2
        exit 1
    fi
done

host_tree="$(cargo tree --locked -p audiagentic-host --edges normal --prefix none)"
for forbidden in audiagentic-config audiagentic-events audiagentic-file-store audiagentic-template audiagentic-reconcile audiagentic-workflow audiagentic-host-native; do
    if printf '%s\n' "$host_tree" | grep -Fq "$forbidden"; then
        echo "HOST_LAYER_LEAK: found $forbidden" >&2
        exit 1
    fi
done

native_host_tree="$(cargo tree --locked -p audiagentic-host-native --edges normal --prefix none)"
for required in audiagentic-host audiagentic-file-store; do
    if ! printf '%s\n' "$native_host_tree" | grep -E "^${required}([[:space:]]|$)" >/dev/null; then
        echo "NATIVE_HOST_LAYER_MISSING: expected $required" >&2
        exit 1
    fi
done
for forbidden in audiagentic-core audiagentic-config audiagentic-events audiagentic-template audiagentic-reconcile audiagentic-workflow; do
    if printf '%s\n' "$native_host_tree" | grep -E "^${forbidden}([[:space:]]|$)" >/dev/null; then
        echo "NATIVE_HOST_LAYER_LEAK: found $forbidden" >&2
        exit 1
    fi
done

events_tree="$(cargo tree --locked -p audiagentic-events --edges normal --prefix none)"
for forbidden in audiagentic-host audiagentic-host-native audiagentic-config audiagentic-file-store audiagentic-reconcile audiagentic-workflow; do
    if printf '%s\n' "$events_tree" | grep -E "^${forbidden}([[:space:]]|$)" >/dev/null; then
        echo "EVENT_LAYER_LEAK: found $forbidden" >&2
        exit 1
    fi
done

workflow_tree="$(cargo tree --locked -p audiagentic-workflow --edges normal --prefix none)"
workflow_lines="$(printf '%s\n' "$workflow_tree" | sed '/^[[:space:]]*$/d' | wc -l)"
if [[ "$workflow_lines" -ne 1 ]]; then
    echo "WORKFLOW_DEPENDENCY_LEAK: workflow primitive must remain pure" >&2
    printf '%s\n' "$workflow_tree" >&2
    exit 1
fi

if grep -R --include='*.rs' -E '\b(Workflow|ComponentProbe|DynApplication|NoWorkflow|NoComponentProbe|CapabilityError|EventBus|ServiceRegistry)\b' crates/audiagentic-core >/dev/null; then
    echo "CORE_DOMAIN_LEAK: rejected capability/framework vocabulary entered audiagentic-core" >&2
    exit 1
fi

if grep -R --include='Cargo.toml' -E '\b(bevy|rmcp|wasmtime|wash-runtime|tokio|async-trait)\b' crates examples >/dev/null; then
    echo "FOUNDATION_RUNTIME_LEAK: runtime/transport dependency entered a production manifest" >&2
    exit 1
fi

if grep -Eq 'audiagentic-file-store' examples/large-app/Cargo.toml || \
   grep -Eq 'audiagentic_file_store' examples/large-app/src/main.rs; then
    echo "LARGE_APP_HOST_BYPASS: large proof must perform state I/O through FileHost" >&2
    exit 1
fi

if grep -R --include='*.rs' -E '\b(EventBus|GlobalEvent|WorkflowRuntime|WorkflowManager)\b' crates/audiagentic-events crates/audiagentic-workflow >/dev/null; then
    echo "CAPABILITY_MANAGER_LEAK: event/workflow primitives must not become global managers" >&2
    exit 1
fi

echo "CORE_LAYER_OK"
echo "FOUNDATION_LIBRARIES_OK"
echo "HOST_BOUNDARY_OK"
echo "NATIVE_FILE_HOST_OK"
echo "NATIVE_PROCESS_HOST_OK"
echo "EVENT_CAPABILITY_OK"
echo "WORKFLOW_CAPABILITY_OK"
echo "APPLICATION_CAPABILITY_COMPOSITION_OK"
echo "TINY_MEDIUM_LARGE_OK"
echo "RUST_PRODUCTION_FOUNDATION_OK"
