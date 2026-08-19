#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cargo test --workspace
cargo build --workspace --release
cargo build --manifest-path components/greeter/Cargo.toml --target wasm32-wasip2 --release

WASM="$ROOT/components/greeter/target/wasm32-wasip2/release/audiagentic_clean_greeter_component.wasm"
MINIMAL="$ROOT/target/release/audiagentic-clean-minimal-app"
MIXED="$ROOT/target/release/audiagentic-clean-mixed-app"
SMOKE=(cargo run --quiet --release -p audiagentic-clean-smoke-client --)

test -f "$WASM"

"${SMOKE[@]}" minimal-stdio "$MINIMAL"
"${SMOKE[@]}" mixed-stdio "$MIXED" "$WASM"

HTTP_LOG="$(mktemp)"
AUDIAGENTIC_MCP_BIND=127.0.0.1:18081 "$MIXED" http "$WASM" >"$HTTP_LOG" 2>&1 &
HTTP_PID=$!
cleanup() {
  kill "$HTTP_PID" 2>/dev/null || true
  wait "$HTTP_PID" 2>/dev/null || true
  rm -f "$HTTP_LOG"
}
trap cleanup EXIT

for _ in $(seq 1 100); do
  if grep -q 'MCP_HTTP_READY=' "$HTTP_LOG"; then break; fi
  if ! kill -0 "$HTTP_PID" 2>/dev/null; then cat "$HTTP_LOG"; exit 1; fi
  sleep 0.1
done
grep -q 'MCP_HTTP_READY=' "$HTTP_LOG" || { cat "$HTTP_LOG"; exit 1; }
"${SMOKE[@]}" mixed-http http://127.0.0.1:18081/mcp

# The minimal application must not pay for the optional heavy runtimes.
cargo tree -p audiagentic-clean-minimal-app > /tmp/audiagentic-minimal-tree.txt
! grep -q 'bevy_ecs' /tmp/audiagentic-minimal-tree.txt
! grep -q 'wasmtime' /tmp/audiagentic-minimal-tree.txt

# The mixed application deliberately selects both implementations.
cargo tree -p audiagentic-clean-mixed-app > /tmp/audiagentic-mixed-tree.txt
grep -q 'bevy_ecs' /tmp/audiagentic-mixed-tree.txt
grep -q 'wasmtime' /tmp/audiagentic-mixed-tree.txt

# Simulate a separate application repository: no workspace membership and no
# source inheritance, just ordinary dependencies on the base capability/component crates.
CONSUMER="$(mktemp -d)"
cat > "$CONSUMER/Cargo.toml" <<EOF
[package]
name = "outside-audiagentic-app"
version = "0.1.0"
edition = "2024"

[dependencies]
audiagentic-clean-capabilities = { path = "$ROOT/crates/capabilities" }
audiagentic-clean-native-greeter = { path = "$ROOT/crates/native-greeter" }
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
EOF
mkdir -p "$CONSUMER/src"
cat > "$CONSUMER/src/main.rs" <<'EOF'
use audiagentic_clean_capabilities::Greeting;
use audiagentic_clean_native_greeter::NativeGreeter;

#[tokio::main]
async fn main() {
    let result = NativeGreeter.greet("outside").await.unwrap();
    assert_eq!(result, "native:hello outside");
    println!("OUTSIDE_APP_OK={result}");
}
EOF
cargo run --quiet --manifest-path "$CONSUMER/Cargo.toml"
rm -rf "$CONSUMER"

MINIMAL_BYTES=$(stat -c%s "$MINIMAL")
MIXED_BYTES=$(stat -c%s "$MIXED")
echo "MINIMAL_APP_BYTES=$MINIMAL_BYTES"
echo "MIXED_APP_BYTES=$MIXED_BYTES"
echo "CLEAN_COMPOSITION_SPIKE_OK"
