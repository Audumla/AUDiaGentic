#!/usr/bin/env bash
# In-container runner for the unified CLEAN suite image (Dockerfile.test).
#
# Runs non-mutating, hermetic tests in one pass. This lane is deliberately
# serial: its lifecycle/surface coverage creates real temporary projects and
# invokes mutable component hooks. Those hooks share process registries and
# toolchain caches which are not safe under xdist's parallel test processes.
# Recipe/CLI lifecycle and host-Docker tests use their own fresh images or
# host-side lane; a container cannot provide its own Docker daemon.
set -uo pipefail

exec pytest -m "not mutates_host and not requires_container and not opt_in and not docker" -q
