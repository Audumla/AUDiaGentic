#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for component in workflow-default workflow-alt; do
  rm -rf "$ROOT/components/$component/wit"
  mkdir -p "$ROOT/components/$component/wit"
  cp "$ROOT/wit/workflow/world.wit" "$ROOT/components/$component/wit/world.wit"
done

rm -rf "$ROOT/components/process/wit"
mkdir -p \
  "$ROOT/components/process/wit/deps/audiagentic-workflow" \
  "$ROOT/components/process/wit/deps/audiagentic-host"
cp "$ROOT/components/process/wit.world.template" "$ROOT/components/process/wit/world.wit"
cp "$ROOT/wit/workflow/world.wit" "$ROOT/components/process/wit/deps/audiagentic-workflow/world.wit"
cp "$ROOT/wit/host/world.wit" "$ROOT/components/process/wit/deps/audiagentic-host/world.wit"
