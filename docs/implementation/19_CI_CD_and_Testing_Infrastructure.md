# CI/CD and Testing Infrastructure

## Purpose

Define the mandatory automation and test rules that support Phase 0 through Phase 6.

## MVP tool choices (frozen unless superseded by ADR)

- **Language:** Python 3.11 target, Python 3.10 minimum
- **Package/build metadata:** `pyproject.toml`
- **Test framework:** `pytest`
- **Coverage tool:** `pytest-cov`
- **Schema validator:** `tools/validate_schemas.py`
- **Naming validator:** `tools/validate_ids.py`
- **Dependency validator:** `tools/validate_packet_dependencies.py`
- **Primary CI system:** GitHub Actions

## Required workflow files

- `.github/workflows/ci-contracts.yml`
- `.github/workflows/ci-tests.yml`
- `.github/workflows/ci-destructive-plan.yml`

## CI pipeline stages

### contract-validation
- validate JSON schemas
- validate example fixtures
- validate canonical ids
- validate packet dependency declarations

### unit-tests
- run packet-owned unit tests
- fail on import-time contract drift

### integration-tests
- lifecycle CLI stub
- ledger sync and finalization
- job runner with stub provider seam
- provider selection/health checks when Phase 4 is present

### destructive-plan-tests
Runs in sandbox repos only:
- install `plan`
- update `plan`
- cutover `plan`
- uninstall `plan`

### destructive-apply-tests
Protected or manually triggered:
- install/apply
- cutover/apply
- uninstall/apply

## Test isolation contract

1. Every test gets a unique temp root.
2. Tests must not depend on execution order.
3. Destructive tests must use isolated sandbox repos.
4. Shared runtime paths are forbidden in tests.
5. Failed sandbox preservation is opt-in through an environment variable.
6. Tests must clean up temp state unless failure-preservation is explicitly enabled.

## Phase 0 minimum CI gate

Phase 0 is not complete until CI proves all of the following:
- schemas validate valid fixtures and reject invalid fixtures
- canonical-id validation passes across docs/examples
- packet dependency graph validation passes
- lifecycle CLI stub emits deterministic `plan` output and checkpoint files

## DRAFT future enhancements

- cross-platform CI matrix (Windows/macOS/Linux)
- benchmark gates
- artifact uploads for failed destructive runs
- flaky-test quarantine handling
