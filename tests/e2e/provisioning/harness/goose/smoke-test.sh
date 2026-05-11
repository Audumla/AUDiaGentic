#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../../.." && pwd)"
BIN_DIR="$ROOT/.audiagentic/provisioning/goose/bin"
RUNTIME_DIR="$ROOT/.audiagentic/runtime/goose"
GOOSE_BIN="${GOOSE_BIN:-$BIN_DIR/goose}"

if [ ! -x "$GOOSE_BIN" ]; then
  FOUND="$(find "$BIN_DIR" -maxdepth 2 -type f -name 'goose' -perm -111 2>/dev/null | head -n 1 || true)"
  [ -n "$FOUND" ] && GOOSE_BIN="$FOUND"
fi

if [ ! -x "$GOOSE_BIN" ]; then
  echo "Goose binary not found. Run fetch-goose.sh first." >&2
  exit 1
fi

mkdir -p "$RUNTIME_DIR/sessions" "$RUNTIME_DIR/logs" "$RUNTIME_DIR/config" "$RUNTIME_DIR/state" "$RUNTIME_DIR/data"

export OPENAI_HOST="${OPENAI_HOST:-http://10.10.200.52:13305/v1}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-dummy}"
export GOOSE_PROVIDER="${GOOSE_PROVIDER:-openai}"
export GOOSE_MODEL="${GOOSE_MODEL:-qwen3.5-2b}"
export GOOSE_MODE="${GOOSE_MODE:-chat}"
export GOOSE_MAX_TURNS="${GOOSE_MAX_TURNS:-5}"
export GOOSE_TEMPERATURE="${GOOSE_TEMPERATURE:-0.0}"
export GOOSE_TELEMETRY_ENABLED="${GOOSE_TELEMETRY_ENABLED:-false}"
export GOOSE_PATH_ROOT="${GOOSE_PATH_ROOT:-$RUNTIME_DIR}"

PROMPT="Respond with exactly: audiagentic-goose-local-ok"

echo "Smoke test: $OPENAI_HOST model=$GOOSE_MODEL"

set +e
OUTPUT="$($GOOSE_BIN run -t "$PROMPT" 2>&1)"
STATUS=$?
set -e

printf '%s\n' "$OUTPUT"

if [ "$STATUS" -ne 0 ]; then
  echo "ERROR: goose run failed (status $STATUS)" >&2
  exit "$STATUS"
fi

if ! printf '%s\n' "$OUTPUT" | grep -q "audiagentic-goose-local-ok"; then
  echo "ERROR: smoke phrase not found in output" >&2
  exit 2
fi

echo "Stage 0 smoke test passed."
