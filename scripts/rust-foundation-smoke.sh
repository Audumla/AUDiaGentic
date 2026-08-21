#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() {
    echo "$1" >&2
    exit 1
}

has_package() {
    local tree="$1"
    local package="$2"
    printf '%s\n' "$tree" | grep -E "^${package}([[:space:]]|$)" >/dev/null
}

require_packages() {
    local label="$1"
    local tree="$2"
    shift 2
    local package
    for package in "$@"; do
        if ! has_package "$tree" "$package"; then
            fail "${label}_MISSING: expected ${package}"
        fi
    done
}

forbid_packages() {
    local label="$1"
    local tree="$2"
    shift 2
    local package
    for package in "$@"; do
        if has_package "$tree" "$package"; then
            fail "${label}_LEAK: found ${package}"
        fi
    done
}

cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked

cargo run --locked --quiet -p audiagentic-example-tiny
cargo run --locked --quiet -p audiagentic-example-medium
cargo run --locked --quiet -p audiagentic-example-large
cargo run --locked --quiet -p audiagentic-example-platform

# Core and error vocabulary are the dependency floor.
core_tree="$(cargo tree --locked -p audiagentic-core --edges normal --prefix none)"
core_lines="$(printf '%s\n' "$core_tree" | sed '/^[[:space:]]*$/d' | wc -l)"
[[ "$core_lines" -eq 1 ]] || fail "CORE_DEPENDENCY_LEAK: audiagentic-core must have zero normal dependencies"

errors_tree="$(cargo tree --locked -p audiagentic-errors --edges normal --prefix none)"
errors_lines="$(printf '%s\n' "$errors_tree" | sed '/^[[:space:]]*$/d' | wc -l)"
[[ "$errors_lines" -eq 1 ]] || fail "ERROR_FOUNDATION_LEAK: audiagentic-errors must have zero normal dependencies"

if grep -R --include='*.rs' -E '\b(Workflow|ComponentProbe|DynApplication|NoWorkflow|NoComponentProbe|CapabilityError|EventBus|ServiceRegistry|TimerRuntime|WorkflowRuntime|Diagnostic|Lifecycle)\b' crates/audiagentic-core >/dev/null; then
    fail "CORE_DOMAIN_LEAK: capability/runtime/diagnostic vocabulary entered audiagentic-core"
fi

# No unselected runtime/transport framework may enter the locked workspace.
workspace_tree="$(cargo tree --workspace --locked --edges normal --prefix none)"
for forbidden in bevy rmcp wasmtime wash-runtime tokio async-trait; do
    if has_package "$workspace_tree" "$forbidden"; then
        fail "FOUNDATION_RUNTIME_LEAK: resolved workspace dependency includes $forbidden"
    fi
done
if grep -R --include='Cargo.toml' -E '\b(bevy|rmcp|wasmtime|wash-runtime|tokio|async-trait)\b' crates examples >/dev/null; then
    fail "FOUNDATION_RUNTIME_LEAK: runtime/transport dependency entered a locked manifest"
fi

# Pure foundation semantics may depend on the tiny error vocabulary but not on
# host, native-effect, application-capability, or peer-domain layers.
sensitive_tree="$(cargo tree --locked -p audiagentic-sensitive --edges normal --prefix none)"
require_packages "SENSITIVE_LAYER" "$sensitive_tree" audiagentic-errors
forbid_packages "SENSITIVE_LAYER" "$sensitive_tree" audiagentic-core audiagentic-config audiagentic-events audiagentic-host audiagentic-host-native audiagentic-managed-config audiagentic-reconcile audiagentic-template audiagentic-time audiagentic-workflow

template_tree="$(cargo tree --locked -p audiagentic-template --edges normal --prefix none)"
require_packages "TEMPLATE_LAYER" "$template_tree" audiagentic-errors
forbid_packages "TEMPLATE_LAYER" "$template_tree" audiagentic-core audiagentic-config audiagentic-events audiagentic-host audiagentic-host-native audiagentic-managed-config audiagentic-reconcile audiagentic-sensitive audiagentic-time audiagentic-workflow

reconcile_tree="$(cargo tree --locked -p audiagentic-reconcile --edges normal --prefix none)"
require_packages "RECONCILE_LAYER" "$reconcile_tree" audiagentic-errors
forbid_packages "RECONCILE_LAYER" "$reconcile_tree" audiagentic-core audiagentic-config audiagentic-events audiagentic-host audiagentic-host-native audiagentic-managed-config audiagentic-sensitive audiagentic-template audiagentic-time audiagentic-workflow

config_tree="$(cargo tree --locked -p audiagentic-config --edges normal --prefix none)"
require_packages "CONFIG_LAYER" "$config_tree" audiagentic-errors
forbid_packages "CONFIG_LAYER" "$config_tree" audiagentic-core audiagentic-events audiagentic-host audiagentic-host-native audiagentic-managed-config audiagentic-reconcile audiagentic-sensitive audiagentic-template audiagentic-time audiagentic-workflow
if grep -E 'figment[^\n]*features[^\n]*env' Cargo.toml >/dev/null; then
    fail "CONFIG_CAPABILITY_LEAK: Figment environment support must not be enabled below composition"
fi
if grep -R --include='*.rs' -Fq 'into_value' crates/audiagentic-config; then
    fail "CONFIG_PROVENANCE_ESCAPE: resolved configuration must retain revision/layer provenance"
fi

# Host contains contracts/authorities only. The only proven host facilities are
# file and process; native OS effects belong to host-native.
host_tree="$(cargo tree --locked -p audiagentic-host --edges normal --prefix none)"
require_packages "HOST_LAYER" "$host_tree" audiagentic-sensitive
forbid_packages "HOST_LAYER" "$host_tree" audiagentic-core audiagentic-config audiagentic-events audiagentic-host-native audiagentic-managed-config audiagentic-reconcile audiagentic-template audiagentic-time audiagentic-workflow
if grep -R --include='*.rs' -E '\b(NetworkHost|NetworkAuthority|NetworkRequest|NetworkResponse|SecretHost|SecretAuthority|HostFuture|HostServices|ServiceRegistry)\b' crates/audiagentic-host >/dev/null; then
    fail "HOST_SPECULATION_LEAK: unproven host contracts or service containers entered audiagentic-host"
fi
if grep -R --include='*.rs' -E '\bstd::(fs|process|net)\b' crates/audiagentic-host >/dev/null; then
    fail "HOST_EFFECT_LEAK: host contracts must not perform native effects"
fi

native_host_tree="$(cargo tree --locked -p audiagentic-host-native --edges normal --prefix none)"
require_packages "NATIVE_HOST_LAYER" "$native_host_tree" audiagentic-host
forbid_packages "NATIVE_HOST_LAYER" "$native_host_tree" audiagentic-core audiagentic-config audiagentic-events audiagentic-managed-config audiagentic-reconcile audiagentic-template audiagentic-time audiagentic-workflow
[[ -f crates/audiagentic-host-native/src/file_store.rs ]] || fail "NATIVE_FILE_DURABILITY_MISSING: private durable-file implementation must live in host-native"
if [[ -e crates/audiagentic-file-store/Cargo.toml ]] || grep -R --include='Cargo.toml' -Fq 'audiagentic-file-store' crates examples; then
    fail "OBSOLETE_FILE_STORE_LAYER: durable file effects must remain private to host-native"
fi

# Reusable application capabilities stay semantic and depend only on the narrow
# lower contracts they actually need.
events_tree="$(cargo tree --locked -p audiagentic-events --edges normal --prefix none)"
require_packages "EVENT_LAYER" "$events_tree" audiagentic-core audiagentic-errors
forbid_packages "EVENT_LAYER" "$events_tree" audiagentic-config audiagentic-host audiagentic-host-native audiagentic-managed-config audiagentic-reconcile audiagentic-sensitive audiagentic-template audiagentic-time audiagentic-workflow

workflow_tree="$(cargo tree --locked -p audiagentic-workflow --edges normal --prefix none)"
require_packages "WORKFLOW_LAYER" "$workflow_tree" audiagentic-errors
forbid_packages "WORKFLOW_LAYER" "$workflow_tree" audiagentic-core audiagentic-config audiagentic-events audiagentic-host audiagentic-host-native audiagentic-managed-config audiagentic-reconcile audiagentic-sensitive audiagentic-template audiagentic-time

time_tree="$(cargo tree --locked -p audiagentic-time --edges normal --prefix none)"
require_packages "TIME_LAYER" "$time_tree" audiagentic-errors
forbid_packages "TIME_LAYER" "$time_tree" audiagentic-core audiagentic-config audiagentic-events audiagentic-host audiagentic-host-native audiagentic-managed-config audiagentic-reconcile audiagentic-sensitive audiagentic-template audiagentic-workflow

managed_config_tree="$(cargo tree --locked -p audiagentic-managed-config --edges normal --prefix none)"
require_packages "MANAGED_CONFIG_LAYER" "$managed_config_tree" audiagentic-errors audiagentic-host audiagentic-reconcile
forbid_packages "MANAGED_CONFIG_LAYER" "$managed_config_tree" audiagentic-core audiagentic-config audiagentic-events audiagentic-host-native audiagentic-template audiagentic-time audiagentic-workflow

# Pure semantic layers cannot discover or perform operating-system effects and
# cannot require an observability backend.
semantic_crates=(
    crates/audiagentic-sensitive
    crates/audiagentic-template
    crates/audiagentic-reconcile
    crates/audiagentic-config
    crates/audiagentic-events
    crates/audiagentic-workflow
    crates/audiagentic-time
    crates/audiagentic-managed-config
)
for crate in "${semantic_crates[@]}"; do
    if grep -R --include='*.rs' -E '\bstd::(env|fs|process|net)\b' "$crate" >/dev/null; then
        fail "SEMANTIC_EFFECT_LEAK: $crate must not discover or perform native effects"
    fi
    if grep -R --include='Cargo.toml' -E '\b(tracing|opentelemetry)\b' "$crate" >/dev/null; then
        fail "SEMANTIC_OBSERVABILITY_LEAK: $crate must not require a telemetry backend"
    fi
done
if grep -R --include='*.rs' -Fq 'tracing_subscriber' crates; then
    fail "GLOBAL_SUBSCRIBER_LEAK: libraries must not install or own a tracing subscriber"
fi

# Stable boundary errors are global identifiers even though their Rust error
# types remain domain-owned.
error_code_duplicates="$(grep -Rho --include='*.rs' -E 'ErrorCode::new\("[A-Z0-9-]+"\)' crates \
    | sed -E 's/.*ErrorCode::new\("([A-Z0-9-]+)"\).*/\1/' | sort | uniq -d)"
if [[ -n "$error_code_duplicates" ]]; then
    echo "DUPLICATE_ERROR_CODE: stable error codes must identify exactly one semantic condition" >&2
    printf '%s\n' "$error_code_duplicates" >&2
    exit 1
fi
for crate in audiagentic-sensitive audiagentic-template audiagentic-reconcile audiagentic-config audiagentic-events audiagentic-workflow audiagentic-time audiagentic-managed-config; do
    if ! grep -R --include='*.rs' -Fq 'CodedError for' "crates/$crate"; then
        fail "CODED_ERROR_CONTRACT_MISSING: $crate exposes a reusable boundary without CodedError"
    fi
done

# Public monotonic identities must reject exhaustion rather than panic or wrap.
if grep -R --include='*.rs' -Fq 'event sequence space exhausted' crates/audiagentic-events || \
   grep -R --include='*.rs' -Fq 'self.revision += 1' crates/audiagentic-workflow; then
    fail "MONOTONIC_IDENTITY_WRAP: reusable sequence/revision identity must use checked failure"
fi
if ! grep -R --include='*.rs' -Fq 'SequenceExhausted' crates/audiagentic-events || \
   ! grep -R --include='*.rs' -Fq 'RevisionExhausted' crates/audiagentic-workflow; then
    fail "MONOTONIC_IDENTITY_GUARD_MISSING: event/workflow exhaustion must be explicit"
fi

# Policy is capability-owned and raw config remains at composition.
if ! grep -R --include='*.rs' -Fq 'pub struct EventPolicy' crates/audiagentic-events; then
    fail "EVENT_POLICY_MISSING: event behaviour must be represented as typed policy"
fi
if ! grep -Fq 'ConfigLayers::new()' examples/platform-app/src/main.rs || \
   ! grep -Fq 'EventPolicy::bounded' examples/platform-app/src/main.rs || \
   ! grep -Fq 'EventStream::with_policy' examples/platform-app/src/main.rs; then
    fail "CONFIG_POLICY_PROOF_MISSING: platform proof must show raw config -> typed config -> capability policy"
fi

# Observability is an application-edge concern. The semantic layers expose
# identity/provenance; the application proof owns the subscriber and spans.
if ! grep -Fq 'ExecutionContext::new' examples/platform-app/src/main.rs || \
   ! grep -Fq 'config_revision' examples/platform-app/src/main.rs; then
    fail "OBSERVABILITY_SEAM_MISSING: execution/correlation/config revision must be available at composition"
fi
if ! grep -Fq 'tracing.workspace = true' examples/platform-app/Cargo.toml || \
   ! grep -Fq 'tracing-subscriber.workspace = true' examples/platform-app/Cargo.toml || \
   ! grep -Fq 'info_span!' examples/platform-app/tests/observability.rs || \
   ! grep -Fq 'execution_id' examples/platform-app/tests/observability.rs || \
   ! grep -Fq 'correlation_id' examples/platform-app/tests/observability.rs || \
   ! grep -Fq 'config_revision' examples/platform-app/tests/observability.rs; then
    fail "STRUCTURED_TRACING_PROOF_MISSING: application edge must prove canonical tracing fields"
fi

# No global manager/framework concepts below the application lock line.
if grep -R --include='*.rs' -E '\b(EventBus|GlobalEvent|WorkflowRuntime|WorkflowManager|TimerRuntime|GlobalTimer|ServiceRegistry|CapabilityRegistry|ObservationManager|TelemetryBus|ObservabilityRuntime|GlobalTracer|GlobalLogger|HostServices)\b' \
    crates/audiagentic-errors crates/audiagentic-sensitive crates/audiagentic-template crates/audiagentic-reconcile crates/audiagentic-config crates/audiagentic-host crates/audiagentic-events crates/audiagentic-workflow crates/audiagentic-time crates/audiagentic-managed-config >/dev/null; then
    fail "GLOBAL_MANAGER_LEAK: locked layers must not become platform-wide managers or registries"
fi

echo "CORE_LAYER_OK"
echo "ERROR_CONTRACT_OK"
echo "PURE_FOUNDATION_OK"
echo "FOUNDATION_LIBRARIES_OK"
echo "CONFIG_POLICY_OK"
echo "HOST_BOUNDARY_OK"
echo "NATIVE_FILE_HOST_OK"
echo "NATIVE_PROCESS_HOST_OK"
echo "EVENT_CAPABILITY_OK"
echo "WORKFLOW_CAPABILITY_OK"
echo "TIME_CAPABILITY_OK"
echo "MANAGED_CONFIG_CAPABILITY_OK"
echo "OBSERVABILITY_STANDARD_OK"
echo "APPLICATION_CAPABILITY_COMPOSITION_OK"
echo "LAYER_CONTRACT_OK"
echo "APPLICATION_CAPABILITIES_LOCK_OK"
echo "TINY_MEDIUM_LARGE_OK"
echo "RUST_PRODUCTION_FOUNDATION_OK"
