# AUDiaGentic test runner
# Usage: make <target>
# Requires: docker, python3, pytest

.PHONY: help test test-all test-fast test-unit test-integration test-e2e \
        test-docker test-lsp-docker test-packaging-docker \
        test-providers-docker test-providers-real-docker test-provider-real-one \
        test-provider-lifecycle-docker build-base build-test build-lsp-install \
        build-packaging build-provider-lifecycle clean-docker

PYTHON     ?= python3
PYTEST     ?= $(PYTHON) -m pytest
BASE_IMAGE  = audia-test-base:latest
TEST_IMAGE  = audiagentic-test:latest
LSP_IMAGE   = audiagentic-lsp-install-test:latest
PROVIDER_LIFECYCLE_IMAGE = audiagentic-provider-lifecycle-e2e:latest

# On Windows with Git Bash / MSYS2, Docker Desktop requires Windows-style paths
# for volume mounts (e.g. C:/path, not /c/path). cygpath -m converts MSYS → mixed.
# On Linux/Mac, cygpath is absent and the fallback pwd gives the correct POSIX path.
DOCKER_MOUNT := $(shell cygpath -m "$(CURDIR)" 2>/dev/null || pwd)

	help:
	@echo "Targets:"
	@echo "  test-all             ONE command: host suite (parallel) + docker if a daemon is present"
	@echo "  test-fast            Host suite only, parallel; never touch docker"
	@echo "  test                 Run unit + integration tests (no docker)"
	@echo "  test-unit            Run unit tests only"
	@echo "  test-integration     Run integration tests only"
	@echo "  test-e2e             Run e2e tests only"
	@echo "  test-docker          Run the clean non-mutating suite in docker"
	@echo "  test-packaging-docker Run clean-room wheel/install/server checks in docker"
	@echo "  test-providers-docker Run provider tests in docker"
	@echo "  test-providers-real-docker Run opt-in real provider CLI tests in docker"
	@echo "  test-provider-real-one PROVIDER=<id>  Run one real provider CLI test in isolated docker"
	@echo "  test-provider-lifecycle-docker Run provider lifecycle/Hindsight/prompt-launch docker image"
	@echo "  test-lsp-docker      Run LSP installation test in docker"
	@echo "  build-base           Build audia-test-base image"
	@echo "  build-test           Build audiagentic-test image (requires base)"
	@echo "  build-lsp-install    Build LSP install test image (requires base)"
	@echo "  build-packaging      Build clean-room packaging image"
	@echo "  build-provider-lifecycle Build provider lifecycle docker image"
	@echo "  clean-docker         Remove all audia test images"

# ── Consolidated entrypoint ──────────────────────────────────────────────────
# tests/run_all.py is the single front door: it runs the whole host suite in
# parallel (the no_parallel hook keeps stateful modules serial) and, when a
# Docker daemon is reachable, builds the image set once and runs the in-container
# suites. Cross-platform — no make dependency on Windows.

test-all:
	$(PYTHON) tests/run_all.py

test-fast:
	$(PYTHON) tests/run_all.py --fast

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
	docker build -f tests/docker/Dockerfile.test-base -t $(BASE_IMAGE) .

build-test: build-base
	docker build -f tests/docker/Dockerfile.test -t $(TEST_IMAGE) .

build-lsp-install: build-base
	docker build -f tests/docker/Dockerfile.lsp-install-test -t $(LSP_IMAGE) .

PACKAGING_IMAGE = audia-packaging:latest

# Clean-room packaging image is intentionally NOT built FROM the toolchain base —
# it proves the wheel is self-contained without the dev toolchain present.
build-packaging:
	docker build -f tests/docker/Dockerfile.packaging -t $(PACKAGING_IMAGE) .

build-provider-lifecycle: build-base
	docker build -f tests/docker/Dockerfile.provider-lifecycle-e2e -t $(PROVIDER_LIFECYCLE_IMAGE) .

# ── Docker test run targets ──────────────────────────────────────────────────

# Runs the whole CLEAN, non-mutating suite inside the standard test image
# (run_suite.sh: -m "not mutates_host" -n auto). Mutating recipe tests run in
# their own isolated images (test-providers-*, test-lsp-docker).
# Uses COPY-based image — rebuild with: make build-test
test-docker: build-test
	docker run --rm $(TEST_IMAGE)

# Clean-room wheel/install/server checks (merged install + release + server-smoke).
test-packaging-docker: build-packaging
	docker run --rm $(PACKAGING_IMAGE)

# Runs provider integration tests in Docker without real mutating provider CLI
# installs unless explicitly opted in at invocation time.
test-providers-docker: build-test
	docker run --rm $(TEST_IMAGE) pytest tests/integration/providers -q

# Runs real provider CLI install/uninstall coverage in Docker.
# This mutates only the container environment, never the host.
# Each provider runs in a fresh container for determinism.
test-providers-real-docker: build-test
	$(PYTHON) tests/dev/run_provider_cli_isolated.py --image $(TEST_IMAGE)

test-provider-real-one: build-test
	$(PYTHON) tests/dev/run_provider_cli_isolated.py --image $(TEST_IMAGE) --provider $(PROVIDER)

# Runs isolated provider lifecycle coverage image.
# Supports passing provider prompt-launch env vars directly to `docker run`, e.g.:
#   OPENAI_API_KEY=... AUDIAGENTIC_TEST_CODEX_MODEL=... make test-provider-lifecycle-docker
test-provider-lifecycle-docker: build-provider-lifecycle
	$(PYTHON) tests/dev/run_provider_lifecycle_docker.py --image $(PROVIDER_LIFECYCLE_IMAGE)

# Validates LSP dependency installation from a clean toolchain state.
# Source is bind-mounted so no rebuild needed for code changes.
test-lsp-docker: build-lsp-install
	docker run --rm -v "$(DOCKER_MOUNT):/app" $(LSP_IMAGE)

# Shell stdout capture on Linux is now covered by the clean suite image
# (run_suite.sh runs the test_steps.py shell case inside Linux). The host-side
# e2e wrapper invokes that same image; no dedicated shell image is needed.

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean-docker:
	-docker rmi $(BASE_IMAGE) $(TEST_IMAGE) $(LSP_IMAGE) $(PACKAGING_IMAGE) $(PROVIDER_LIFECYCLE_IMAGE) 2>/dev/null || true
