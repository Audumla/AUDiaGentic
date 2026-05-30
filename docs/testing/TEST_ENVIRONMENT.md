# Test Environment

This repo uses two test modes:

- local fast tests for unit and non-mutating integration work
- Docker-gated tests for anything that installs tools, writes lifecycle state, or mutates runtime environments

Related structure guide:

- `docs/testing/TEST_ARCHITECTURE.md`

This document is source of truth for agents and developers extending tests.

## Core Rules

- Do not run mutating provider CLI install tests on host machine.
- Real provider CLI tests must run in Docker with:
  - `AUDIAGENTIC_DOCKER_TESTS=1`
  - `AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS=1`
- Prefer bind-mounted Docker runs for code iteration.
- Rebuild Docker images only when image inputs changed.

## Main Images

- `audia-test-base:latest`
  - base toolchain image
  - used for fast bind-mounted validation
- `audiagentic-test:latest`
  - copy-based test image
  - good for stable full-suite runs
- `audiagentic-lsp-install-test:latest`
  - LSP-specific install validation

## Common Commands

Local fast path:

```bash
pytest tests/unit -q
pytest tests/integration -q
```

Build images:

```bash
make build-base
make build-test
make build-lsp-install
```

Docker provider tests:

```bash
make test-providers-docker
make test-providers-real-docker
make test-provider-real-one PROVIDER=codex
```

Full Docker suite:

```bash
make test-docker
```

## Provider CLI Tests

Provider CLI lifecycle coverage is centralized under:

- `tests/integration/providers/harness.py`
- `tests/integration/providers/harness.yaml`

Use harness helpers instead of open-coding:

- provider selection
- install/uninstall roundtrip
- project-root setup
- probe/health behavior
- cleanup
- Docker skip rules

### Add New Provider Test Coverage

1. Add or update provider descriptor under `src/audiagentic/components/optional/providers/adapters/...`
2. Add workflow resource in `src/audiagentic/components/optional/providers/workflow/provider_cli.yaml`
3. If provider needs special test behavior, add policy entry in `tests/integration/providers/harness.yaml`
4. Reuse existing generic tests before writing provider-specific tests
5. Add provider-specific test only when behavior is not covered by shared harness

### When To Add Harness Policy

Add `harness.yaml` policy only for cross-cutting runtime needs such as:

- requires temp project root
- requires `code` CLI
- Docker-only skip reason
- non-default trust in install probe
- future per-provider health/install timeout overrides

Do not add policy for ordinary package manager behavior.

## Workflow-Backed Provider Coverage

Shared workflow coverage lives in:

- `tests/unit/providers/test_provider_cli_workflow.py`
- `tests/integration/providers/test_provider_cli_workflow_docker.py`

Expectation:

- every installable provider is workflow-backed
- install/uninstall commands come from workflow config
- real Docker roundtrip uses workflow path, not ad hoc provider logic

## How Real Provider Tests Are Gated

Repository test collection skips `mutates_host` tests unless both env vars are set:

- `AUDIAGENTIC_DOCKER_TESTS=1`
- `AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS=1`

This protects local developer environments.

## Official Real-CLI Path

Shared-container real CLI runs are no longer preferred for maintenance work.

Use fresh-container-per-provider isolation:

```bash
make test-providers-real-docker
```

Run one provider while iterating:

```bash
make test-provider-real-one PROVIDER=codex
```

Implementation entrypoint:

- `tests/dev/run_provider_cli_isolated.py`

This runner:

- starts one clean container per provider
- uses copy-based test image by default for determinism
- retries failed providers once in a fresh container
- sets real-test gating env vars
- narrows collection with `AUDIAGENTIC_PROVIDER_UNDER_TEST`

Use this path when debugging flaky CLI installs, probes, or uninstall flows.

Use bind-mounted iteration only when you need fast local edits:

```bash
python tests/dev/run_provider_cli_isolated.py --image audiagentic-test:latest --provider codex --bind-mount
```

This is less deterministic than copy-based mode.

## Bind-Mounted Docker Iteration

Best when changing Python code or tests without rebuilding image:

```bash
docker run --rm \
  -v "${PWD}:/app" \
  -w /app \
  -e PYTHONPATH=/app/src \
  -e AUDIAGENTIC_DOCKER_TESTS=1 \
  -e AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS=1 \
  audiagentic-test:latest \
  pytest tests/integration/providers -q
```

Note:

- some workflows need patched `code` wrapper behavior already present in Docker test setup
- if Docker image changed, rebuild first
- prefer isolated provider runner for real install/uninstall coverage
- prefer copy-based isolated runs for VS Code extension providers and flaky npm CLIs

## Rebuild Threshold

Rebuild test images when any of these changed:

- `tests/docker/Dockerfile.test-base`
- `tests/docker/Dockerfile.test`
- `tests/docker/Dockerfile.lsp-install-test`
- OS packages
- preinstalled CLIs
- Python package bootstrap in image

Do not rebuild for ordinary Python source/test edits when bind mount is enough.

## Current Expected Skips

These are acceptable and documented:

- Claude hook-chain tests when local `.claude/settings.json` lacks hooks
- `plandex` real Docker install due interactive GitHub tap auth
- explicit empty-parameter pytest cases

If a new skip appears, document reason or fix it.

Known non-skip instability:

- some npm-backed CLIs can still fail intermittently in exhaustive all-provider sweeps due upstream/native install crashes or network behavior
- validate those providers individually before treating the issue as workflow regression

## Extension Pattern

If another component family needs lifecycle/install testing:

1. create component-specific harness module
2. keep policy/config in YAML
3. move install/probe/uninstall logic into helpers
4. keep generic roundtrip tests data-driven
5. add small unit tests for harness config contract

This is preferred over copying provider test structure by hand.

## Add New Harness Coverage

When extending harness-driven tests:

1. put selection/policy data in `harness.yaml` when logic is shared
2. add unit tests that validate config keys reference real registry IDs
3. add integration tests that consume harness selectors rather than hand-built lists
4. add provider/component-specific tests only for behavior shared harness cannot express
