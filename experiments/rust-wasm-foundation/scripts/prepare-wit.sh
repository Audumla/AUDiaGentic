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
  "$ROOT/components/process/wit/deps/audiagentic-host" \
  "$ROOT/components/process/wit/deps/http"
cp "$ROOT/components/process/wit.world.template" "$ROOT/components/process/wit/world.wit"
cp "$ROOT/wit/workflow/world.wit" "$ROOT/components/process/wit/deps/audiagentic-workflow/world.wit"
cp "$ROOT/wit/host/world.wit" "$ROOT/components/process/wit/deps/audiagentic-host/world.wit"

# Cargo + wit-bindgen intentionally build the component directly, without the
# wash CLI. Materialize the exact official WIT dependency tree consumed by
# wasi:http@0.2.2 so the component contract is still reproducible.
WASI_HTTP_REF="v0.2.2"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone --quiet --depth 1 --branch "$WASI_HTTP_REF" \
  https://github.com/WebAssembly/wasi-http.git "$TMP/wasi-http"
cp "$TMP/wasi-http/wit/handler.wit" "$ROOT/components/process/wit/deps/http/handler.wit"
cp "$TMP/wasi-http/wit/proxy.wit" "$ROOT/components/process/wit/deps/http/proxy.wit"
cp "$TMP/wasi-http/wit/types.wit" "$ROOT/components/process/wit/deps/http/types.wit"
for dep in cli clocks filesystem io random sockets; do
  cp -R "$TMP/wasi-http/wit/deps/$dep" "$ROOT/components/process/wit/deps/$dep"
done
