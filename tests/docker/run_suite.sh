#!/usr/bin/env bash
# In-container runner for the unified CLEAN suite image (Dockerfile.test).
#
# Runs the whole NON-mutating suite in one parallel pass — the non-Docker tests
# do not care that they happen to be inside a container, so we run them here too
# rather than a hand-picked subset. The no_parallel hook in tests/conftest.py
# keeps stateful modules serial-on-one-worker, so -n auto is safe.
#
# mutates_host tests are EXCLUDED on purpose: they exercise real MCP install
# recipes and assert install/uninstall from a clean toolchain. Running them in a
# shared container would leak server/CLI state between tests and invalidate those
# assertions, so they run only in their own isolated images / fresh containers.
set -uo pipefail

exec pytest -m "not mutates_host" -n auto --dist loadgroup -q
