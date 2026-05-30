# Test Architecture

This document explains how test code should be structured in this repo so new
coverage can be added without duplicating lifecycle logic or embedding fragile
environment assumptions in individual test files.

## Goals

- maximize reuse of install/probe/cleanup flows
- keep environment-specific behavior in one place
- make new tests mostly config-driven
- ensure Docker-gated tests never mutate host machine state

## Preferred Layers

### 1. Descriptor or config contract tests

Use unit tests first to validate:

- config loads
- workflow resources exist
- provider/component IDs match registry
- commands render from config as expected

These should be cheap and deterministic.

Examples:

- `tests/unit/providers/test_provider_cli_workflow.py`
- `tests/unit/providers/test_provider_test_harness.py`
- `tests/unit/lifecycle/test_lifecycle_test_harness.py`

### 2. Shared harness helpers

If multiple tests need same lifecycle behavior, create a harness module.

Harness owns:

- provider/component selection
- environment setup
- skip policy
- install/uninstall wrappers
- health/probe assertions
- cleanup

Current example:

- `tests/integration/providers/harness.py`
- `tests/integration/lifecycle/harness.py`

### 3. Harness policy/config

If behavior changes by provider/component but logic is same, use YAML config.

Keep policy/config for:

- Docker-only skip reasons
- temp project-root requirements
- runtime prerequisites like `code`
- trust in install probe
- future timeout or health strategy overrides

Current example:

- `tests/integration/providers/harness.yaml`
- `tests/integration/lifecycle/harness.yaml`

### 4. Generic integration tests

Write generic roundtrip tests that iterate over descriptor/config data rather
than hand-maintained provider lists when possible.

Good:

- select by package manager from registry
- assert workflow coverage for all installable items
- reuse harness methods for install/uninstall
- narrow isolated runs through env-driven selectors instead of editing test code

Avoid:

- copying same install/probe/cleanup sequence across files
- hard-coding provider IDs when registry/config can derive them

## When Provider-Specific Tests Are Justified

Add provider-specific tests only when provider has unique behavior not covered
by shared harness, for example:

- custom config file format
- special prompt/rule file generation
- provider-specific MCP layout
- non-standard auth/CLI command behavior

## Docker Testing Pattern

For mutating tests:

- run in Docker only
- prefer bind-mounted source for iteration
- rebuild images only when image inputs change
- prefer one clean container per real provider CLI when install/uninstall is under test
- prefer copy-based isolated containers as default execution path
- reserve bind-mount mode for active debugging, not baseline validation

Commands and rules live in:

- `docs/testing/TEST_ENVIRONMENT.md`

## Layer Separation

Keep these concerns separate:

- descriptor/config contract tests
- harness config contract tests
- generic integration roundtrip tests
- real Docker install/uninstall runs

Do not force production code to expose test-only seams when one of these layers can
cover behavior already.

If real Docker coverage is flaky:

- first isolate container state
- next switch from bind-mounted to copy-based image runs
- then tune harness policy/config
- only then reconsider production behavior

## Extension Pattern For New Component Families

If another component family needs install/lifecycle testing:

1. create `tests/integration/<family>/harness.py`
2. create optional `harness.yaml`
3. add unit tests validating harness config contract
4. refactor lifecycle tests to use harness before adding more coverage
5. document commands in `docs/testing/TEST_ENVIRONMENT.md`

## Maintenance Rule

When a test needs a new environment quirk:

- first ask if it belongs in descriptor/config
- next ask if it belongs in harness policy YAML
- only then add Python branching in a test file

This keeps tests slimmer and easier to evolve.

## Adding New Coverage

For new provider or component families:

1. extend registry/descriptor first
2. extend workflow/config if lifecycle is config-backed
3. add or update harness YAML only for shared environment/runtime quirks
4. add unit tests for selector/policy contract
5. add generic integration coverage through harness selectors
6. add targeted family-specific tests only for unique behavior
