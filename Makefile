# AUDiaGentic test runner
# Usage: make <target>
# Requires: docker, python3, pytest

.PHONY: help test test-unit test-integration test-e2e test-docker test-lsp-docker \
        test-providers-docker test-providers-real-docker \
        build-base build-test build-lsp-install-test clean-docker

PYTHON     ?= python3
PYTEST     ?= $(PYTHON) -m pytest
BASE_IMAGE  = audia-test-base:latest
TEST_IMAGE  = audiagentic-test:latest
LSP_IMAGE   = audiagentic-lsp-install-test:latest

# On Windows with Git Bash / MSYS2, Docker Desktop requires Windows-style paths
# for volume mounts (e.g. C:/path, not /c/path). cygpath -m converts MSYS → mixed.
# On Linux/Mac, cygpath is absent and the fallback pwd gives the correct POSIX path.
DOCKER_MOUNT := $(shell cygpath -m "$(CURDIR)" 2>/dev/null || pwd)

help:
	@echo "Targets:"
	@echo "  test                 Run unit + integration tests (no docker)"
	@echo "  test-unit            Run unit tests only"
	@echo "  test-integration     Run integration tests only"
	@echo "  test-e2e             Run e2e tests only"
	@echo "  test-docker          Run all docker-based tests"
	@echo "  test-providers-docker Run provider tests in docker"
	@echo "  test-providers-real-docker Run opt-in real provider CLI tests in docker"
	@echo "  test-lsp-docker      Run LSP installation test in docker"
	@echo "  build-base           Build audia-test-base image"
	@echo "  build-test           Build audiagentic-test image (requires base)"
	@echo "  build-lsp-install    Build LSP install test image (requires base)"
	@echo "  clean-docker         Remove all audia test images"

# ── Local test targets ───────────────────────────────────────────────────────

test: test-unit test-integration

test-unit:
	$(PYTEST) tests/unit -q --tb=short

test-integration:
	$(PYTEST) tests/integration -q --tb=short

test-e2e:
	$(PYTEST) tests/e2e -q --tb=short

test-slow:
	$(PYTEST) -m slow -q --tb=short

# ── Docker image build targets ───────────────────────────────────────────────

build-base:
	docker build -f Dockerfile.test-base -t $(BASE_IMAGE) .

build-test: build-base
	docker build -f Dockerfile.test -t $(TEST_IMAGE) .

build-lsp-install: build-base
	docker build -f Dockerfile.lsp-install-test -t $(LSP_IMAGE) .

# ── Docker test run targets ──────────────────────────────────────────────────

# Runs unit + integration + e2e inside the standard test image.
# Uses COPY-based image — rebuild with: make build-test
test-docker: build-test
	docker run --rm $(TEST_IMAGE)

# Runs provider integration tests in Docker without real mutating provider CLI
# installs unless explicitly opted in at invocation time.
test-providers-docker: build-test
	docker run --rm $(TEST_IMAGE) pytest tests/integration/providers -q

# Runs real provider CLI install/uninstall coverage in Docker.
# This mutates only the container environment, never the host.
test-providers-real-docker: build-test
	docker run --rm -e AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS=1 $(TEST_IMAGE) pytest tests/integration/providers -q

# Validates LSP dependency installation from a clean toolchain state.
# Source is bind-mounted so no rebuild needed for code changes.
test-lsp-docker: build-lsp-install
	docker run --rm -v "$(DOCKER_MOUNT):/app" $(LSP_IMAGE)

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean-docker:
	-docker rmi $(BASE_IMAGE) $(TEST_IMAGE) $(LSP_IMAGE) 2>/dev/null || true
