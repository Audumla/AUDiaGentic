#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cargo test --workspace
cargo build --workspace --release

./target/release/bevy-runtime-smoke

./target/release/audiagentic-mcp-smoke \
  stdio \
  ./target/release/audiagentic-bevy-mcp-stdio

HTTP_LOG="$(mktemp)"
AUDIAGENTIC_MCP_BIND=127.0.0.1:18080 \
  ./target/release/audiagentic-bevy-mcp-http >"$HTTP_LOG" 2>&1 &
HTTP_PID=$!
cleanup() {
  if kill -0 "$HTTP_PID" 2>/dev/null; then
    kill -INT "$HTTP_PID" 2>/dev/null || true
    wait "$HTTP_PID" 2>/dev/null || true
  fi
  rm -f "$HTTP_LOG"
}
trap cleanup EXIT

for _ in $(seq 1 60); do
  if grep -q 'MCP_HTTP_READY=' "$HTTP_LOG"; then
    break
  fi
  if ! kill -0 "$HTTP_PID" 2>/dev/null; then
    cat "$HTTP_LOG"
    echo "HTTP MCP server exited before becoming ready" >&2
    exit 1
  fi
  sleep 0.25
done

grep 'MCP_HTTP_READY=' "$HTTP_LOG"
./target/release/audiagentic-mcp-smoke \
  http \
  http://127.0.0.1:18080/mcp

kill -INT "$HTTP_PID" 2>/dev/null || true
wait "$HTTP_PID" || true
trap - EXIT
rm -f "$HTTP_LOG"

SIMPLE_BYTES=$(stat -c '%s' ./target/release/audiagentic-simple-mcp-stdio)
BEVY_STDIO_BYTES=$(stat -c '%s' ./target/release/audiagentic-bevy-mcp-stdio)
BEVY_HTTP_BYTES=$(stat -c '%s' ./target/release/audiagentic-bevy-mcp-http)

echo "SIMPLE_MCP_BYTES=$SIMPLE_BYTES"
echo "BEVY_MCP_STDIO_BYTES=$BEVY_STDIO_BYTES"
echo "BEVY_MCP_HTTP_BYTES=$BEVY_HTTP_BYTES"
echo "BEVY_MCP_SPIKE_OK"
