#!/usr/bin/env bash
# In-container runner for the unified CLEAN suite image (Dockerfile.test).
#
# Runs non-mutating, hermetic tests in two phases. Most tests run in parallel;
# modules marked no_parallel are held back and then run in one serial phase.
# Recipe/CLI lifecycle and host-Docker tests use their own fresh images or
# host-side lane; a container cannot provide its own Docker daemon.
set -uo pipefail

BASE_MARK="not mutates_host and not requires_container and not opt_in and not docker"

pytest -n "${AUDIAGENTIC_XDIST_WORKERS:-8}" --dist loadgroup -m "(${BASE_MARK}) and not no_parallel" -q
parallel_rc=$?

AUDIAGENTIC_SERIAL_PHASE=1 pytest -m "(${BASE_MARK}) and no_parallel" -q
serial_rc=$?

if [[ "$parallel_rc" -ne 0 || "$serial_rc" -ne 0 ]]; then
    exit 1
fi
