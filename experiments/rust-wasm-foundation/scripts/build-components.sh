#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/scripts/prepare-wit.sh"

for component in workflow-default workflow-alt process; do
  echo "==> building $component"
  cargo build \
    --manifest-path "$ROOT/components/$component/Cargo.toml" \
    --target wasm32-wasip2 \
    --release
done
