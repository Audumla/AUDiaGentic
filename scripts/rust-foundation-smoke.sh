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
cargo run --locked --quiet -p audiagentic-example-platform

core_tree="$(cargo tree --locked -p audiagentic-core --edges normal --prefix none)"
core_lines="$(printf '%s\n' "$core_tree" | sed '/^[[:space:]]*$/d' | wc -l)"
if [[ "$core_lines" -ne 1 ]]; then
    echo "CORE_DEPENDENCY_LEAK: audiagentic-core must have zero normal dependencies" >&2
    printf '%s\n' "$core_tree" >&2
    exit 1
fi

errors_tree="$(cargo tree --locked -p audiagentic-errors --edges normal --prefix none)"
errors_lines="$(printf '%s\n' "$errors_tree" | sed '/^[[:space:]]*$/d' | wc -l)"
if [[ "$errors_lines" -ne 1 ]]; then
    echo "ERROR_FOUNDATION_LEAK: audiagentic-errors must have zero normal dependencies" >&2
    printf '%s\n' "$errors_tree" >&2
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
for forbidden in audiagentic-config audiagentic-errors audiagentic-events audiagentic-file-store audiagentic-template audiagentic-reconcile audiagentic-time audiagentic-workflow audiagentic-managed-config audiagentic-host-native; do
    if printf '%s\n' "$host_tree" | grep -Fq "$forbidden"; then
        echo "HOST_LAYER_LEAK: found $forbidden" >&2
        exit 1
    fi
done
if grep -R --include='*.rs' -E '\b(NetworkHost|NetworkAuthority|NetworkRequest|NetworkResponse|SecretHost|SecretAuthority|HostFuture)\b' crates/audiagentic-host >/dev/null; then
    echo "HOST_SPECULATION_LEAK: unproven network/secret host contracts entered the locked host layer" >&2
    exit 1
fi

native_host_tree="$(cargo tree --locked -p audiagentic-host-native --edges normal --prefix none)"
for required in audiagentic-host audiagentic-file-store; do
    if ! printf '%s\n' "$native_host_tree" | grep -E "^${required}([[:space:]]|$)" >/dev/null; then
        echo "NATIVE_HOST_LAYER_MISSING: expected $required" >&2
        exit 1
    fi
done
for forbidden in audiagentic-core audiagentic-config audiagentic-errors audiagentic-events audiagentic-template audiagentic-reconcile audiagentic-time audiagentic-workflow audiagentic-managed-config; do
    if printf '%s\n' "$native_host_tree" | grep -E "^${forbidden}([[:space:]]|$)" >/dev/null; then
        echo "NATIVE_HOST_LAYER_LEAK: found $forbidden" >&2
        exit 1
    fi
done

config_tree="$(cargo tree --locked -p audiagentic-config --edges normal --prefix none)"
if ! printf '%s\n' "$config_tree" | grep -E '^audiagentic-errors([[:space:]]|$)' >/dev/null; then
    echo "CONFIG_ERROR_CONTRACT_MISSING: expected audiagentic-errors" >&2
    exit 1
fi
for forbidden in audiagentic-core audiagentic-events audiagentic-file-store audiagentic-host audiagentic-host-native audiagentic-managed-config audiagentic-reconcile audiagentic-sensitive audiagentic-template audiagentic-time audiagentic-workflow; do
    if printf '%s\n' "$config_tree" | grep -E "^${forbidden}([[:space:]]|$)" >/dev/null; then
        echo "CONFIG_LAYER_LEAK: found $forbidden" >&2
        exit 1
    fi
done
if grep -E 'figment[^\n]*features[^\n]*env' Cargo.toml >/dev/null; then
    echo "CONFIG_CAPABILITY_LEAK: Figment environment support must not be enabled below composition" >&2
    exit 1
fi
if grep -R --include='*.rs' -Fq 'into_value' crates/audiagentic-config; then
    echo "CONFIG_PROVENANCE_ESCAPE: resolved configuration must retain revision/layer provenance" >&2
    exit 1
fi

events_tree="$(cargo tree --locked -p audiagentic-events --edges normal --prefix none)"
for required in audiagentic-core audiagentic-errors; do
    if ! printf '%s\n' "$events_tree" | grep -E "^${required}([[:space:]]|$)" >/dev/null; then
        echo "EVENT_LAYER_MISSING: expected $required" >&2
        exit 1
    fi
done
for forbidden in audiagentic-host audiagentic-host-native audiagentic-config audiagentic-file-store audiagentic-reconcile audiagentic-sensitive audiagentic-template audiagentic-time audiagentic-workflow audiagentic-managed-config; do
    if printf '%s\n' "$events_tree" | grep -E "^${forbidden}([[:space:]]|$)" >/dev/null; then
        echo "EVENT_LAYER_LEAK: found $forbidden" >&2
        exit 1
    fi
done

workflow_tree="$(cargo tree --locked -p audiagentic-workflow --edges normal --prefix none)"
if ! printf '%s\n' "$workflow_tree" | grep -E '^audiagentic-errors([[:space:]]|$)' >/dev/null; then
    echo "WORKFLOW_ERROR_CONTRACT_MISSING: expected audiagentic-errors" >&2
    exit 1
fi
for forbidden in audiagentic-core audiagentic-config audiagentic-events audiagentic-file-store audiagentic-host audiagentic-host-native audiagentic-managed-config audiagentic-reconcile audiagentic-sensitive audiagentic-template audiagentic-time; do
    if printf '%s\n' "$workflow_tree" | grep -E "^${forbidden}([[:space:]]|$)" >/dev/null; then
        echo "WORKFLOW_DEPENDENCY_LEAK: found $forbidden" >&2
        exit 1
    fi
done

time_tree="$(cargo tree --locked -p audiagentic-time --edges normal --prefix none)"
if ! printf '%s\n' "$time_tree" | grep -E '^audiagentic-errors([[:space:]]|$)' >/dev/null; then
    echo "TIME_ERROR_CONTRACT_MISSING: expected audiagentic-errors" >&2
    exit 1
fi
for forbidden in audiagentic-core audiagentic-config audiagentic-events audiagentic-file-store audiagentic-host audiagentic-host-native audiagentic-managed-config audiagentic-reconcile audiagentic-sensitive audiagentic-template audiagentic-workflow; do
    if printf '%s\n' "$time_tree" | grep -E "^${forbidden}([[:space:]]|$)" >/dev/null; then
        echo "TIME_DEPENDENCY_LEAK: found $forbidden" >&2
        exit 1
    fi
done

managed_config_tree="$(cargo tree --locked -p audiagentic-managed-config --edges normal --prefix none)"
for required in audiagentic-errors audiagentic-host audiagentic-reconcile; do
    if ! printf '%s\n' "$managed_config_tree" | grep -E "^${required}([[:space:]]|$)" >/dev/null; then
        echo "MANAGED_CONFIG_LAYER_MISSING: expected $required" >&2
        exit 1
    fi
done
for forbidden in audiagentic-core audiagentic-config audiagentic-events audiagentic-file-store audiagentic-host-native audiagentic-template audiagentic-time audiagentic-workflow; do
    if printf '%s\n' "$managed_config_tree" | grep -E "^${forbidden}([[:space:]]|$)" >/dev/null; then
        echo "MANAGED_CONFIG_LAYER_LEAK: found $forbidden" >&2
        exit 1
    fi
done

if grep -R --include='*.rs' -E '\b(Workflow|ComponentProbe|DynApplication|NoWorkflow|NoComponentProbe|CapabilityError|EventBus|ServiceRegistry|TimerRuntime|WorkflowRuntime)\b' crates/audiagentic-core >/dev/null; then
    echo "CORE_DOMAIN_LEAK: rejected capability/framework vocabulary entered audiagentic-core" >&2
    exit 1
fi

if grep -R --include='Cargo.toml' -E '\b(bevy|rmcp|wasmtime|wash-runtime|tokio|async-trait)\b' crates examples >/dev/null; then
    echo "FOUNDATION_RUNTIME_LEAK: runtime/transport dependency entered a production manifest" >&2
    exit 1
fi

semantic_crates=(
    crates/audiagentic-config
    crates/audiagentic-events
    crates/audiagentic-workflow
    crates/audiagentic-time
    crates/audiagentic-managed-config
    crates/audiagentic-reconcile
    crates/audiagentic-sensitive
    crates/audiagentic-template
)
for crate in "${semantic_crates[@]}"; do
    if grep -R --include='*.rs' -E '\bstd::(env|fs)\b' "$crate" >/dev/null; then
        echo "RAW_CONFIG_OR_IO_LEAK: $crate must not discover environment/filesystem sources directly" >&2
        exit 1
    fi
    if grep -R --include='Cargo.toml' -E '\b(tracing|opentelemetry)\b' "$crate" >/dev/null; then
        echo "SEMANTIC_OBSERVABILITY_LEAK: $crate must not require a telemetry backend" >&2
        exit 1
    fi
done
if grep -R --include='*.rs' -Fq 'tracing_subscriber' crates; then
    echo "GLOBAL_SUBSCRIBER_LEAK: libraries must not install or own a tracing subscriber" >&2
    exit 1
fi

error_code_duplicates="$(grep -Rho --include='*.rs' -E 'ErrorCode::new\("[A-Z0-9-]+"\)' \
    crates/audiagentic-config crates/audiagentic-errors crates/audiagentic-events crates/audiagentic-workflow crates/audiagentic-time crates/audiagentic-managed-config \
    | sed -E 's/.*ErrorCode::new\("([A-Z0-9-]+)"\).*/\1/' | sort | uniq -d)"
if [[ -n "$error_code_duplicates" ]]; then
    echo "DUPLICATE_ERROR_CODE: stable error codes must identify exactly one semantic condition" >&2
    printf '%s\n' "$error_code_duplicates" >&2
    exit 1
fi

for crate in audiagentic-config audiagentic-events audiagentic-workflow audiagentic-time audiagentic-managed-config; do
    if ! grep -R --include='*.rs' -Fq 'CodedError for' "crates/$crate"; then
        echo "CODED_ERROR_CONTRACT_MISSING: $crate exposes a locked boundary without CodedError" >&2
        exit 1
    fi
done

if ! grep -R --include='*.rs' -Fq 'pub struct EventPolicy' crates/audiagentic-events; then
    echo "EVENT_POLICY_MISSING: event behaviour must be represented as typed policy" >&2
    exit 1
fi
if ! grep -Fq 'ConfigLayers::new()' examples/platform-app/src/main.rs || \
   ! grep -Fq 'EventPolicy::bounded' examples/platform-app/src/main.rs || \
   ! grep -Fq 'EventStream::with_policy' examples/platform-app/src/main.rs; then
    echo "CONFIG_POLICY_PROOF_MISSING: platform proof must show raw config -> typed config -> capability policy" >&2
    exit 1
fi
if ! grep -Fq 'ExecutionContext::new' examples/platform-app/src/main.rs || \
   ! grep -Fq 'config_revision' examples/platform-app/src/main.rs; then
    echo "OBSERVABILITY_SEAM_MISSING: execution/correlation/config revision must be available at composition" >&2
    exit 1
fi
if ! grep -Fq 'tracing.workspace = true' examples/platform-app/Cargo.toml || \
   ! grep -Fq 'tracing-subscriber.workspace = true' examples/platform-app/Cargo.toml || \
   ! grep -Fq 'info_span!' examples/platform-app/tests/observability.rs || \
   ! grep -Fq 'execution_id' examples/platform-app/tests/observability.rs || \
   ! grep -Fq 'correlation_id' examples/platform-app/tests/observability.rs || \
   ! grep -Fq 'config_revision' examples/platform-app/tests/observability.rs; then
    echo "STRUCTURED_TRACING_PROOF_MISSING: application edge must prove canonical tracing fields" >&2
    exit 1
fi

if grep -Eq 'audiagentic-file-store' examples/large-app/Cargo.toml || \
   grep -Eq 'audiagentic_file_store' examples/large-app/src/main.rs; then
    echo "LARGE_APP_HOST_BYPASS: large proof must perform state I/O through FileHost" >&2
    exit 1
fi

if grep -Eq 'audiagentic-file-store' examples/platform-app/Cargo.toml || \
   grep -Eq 'audiagentic_file_store' examples/platform-app/src/main.rs; then
    echo "PLATFORM_APP_HOST_BYPASS: platform proof must perform state I/O through capabilities/host" >&2
    exit 1
fi

if grep -R --include='*.rs' -E '\b(EventBus|GlobalEvent|WorkflowRuntime|WorkflowManager|TimerRuntime|GlobalTimer|ServiceRegistry|ObservationManager|TelemetryBus|ObservabilityRuntime|GlobalTracer|GlobalLogger)\b' \
    crates/audiagentic-errors crates/audiagentic-config crates/audiagentic-events crates/audiagentic-workflow crates/audiagentic-time crates/audiagentic-managed-config >/dev/null; then
    echo "CAPABILITY_MANAGER_LEAK: locked semantic layers must not become global managers" >&2
    exit 1
fi

echo "CORE_LAYER_OK"
echo "ERROR_CONTRACT_OK"
echo "FOUNDATION_LIBRARIES_OK"
echo "CONFIG_POLICY_OK"
echo "OBSERVABILITY_STANDARD_OK"
echo "HOST_BOUNDARY_OK"
echo "NATIVE_FILE_HOST_OK"
echo "NATIVE_PROCESS_HOST_OK"
echo "EVENT_CAPABILITY_OK"
echo "WORKFLOW_CAPABILITY_OK"
echo "TIME_CAPABILITY_OK"
echo "MANAGED_CONFIG_CAPABILITY_OK"
echo "APPLICATION_CAPABILITY_COMPOSITION_OK"
echo "APPLICATION_CAPABILITIES_LOCK_OK"
echo "TINY_MEDIUM_LARGE_OK"
echo "RUST_PRODUCTION_FOUNDATION_OK"
