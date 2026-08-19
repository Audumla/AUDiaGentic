#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/../.." && pwd)"

bash "$ROOT/scripts/architecture.sh"

"$REPO_ROOT/experiments/rust-wasm-foundation/scripts/smoke.sh"
WASM_BIN="$REPO_ROOT/experiments/rust-wasm-foundation/host/target/release/audiagentic-rust-wasm-smoke"
test -x "$WASM_BIN"

cd "$ROOT"
AUDIAGENTIC_WASM_SMOKE_BIN="$WASM_BIN" cargo run -p audiagentic-clean-baseline-smoke --release

echo "RUST_BASELINE_V2_SMOKE_OK"
