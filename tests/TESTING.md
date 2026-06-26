# Testing Standards

Covers: folder structure, test tiers, markers, naming, assertions, fixtures,
timeouts, coverage, Docker conventions, and CI execution matrix.

---

## Folder structure

```text
tests/
├── unit/           Fast, isolated — no subprocess, no real I/O, no network
├── integration/    Real I/O — filesystem (tmp_path), subprocess, local services
├── e2e/            Full user-facing path — real CLI, Docker, external systems
├── deferred/       Tests for planned/unbuilt modules — never collected in CI
├── dev/            Local developer checks against checkout state — never in CI
├── helpers/        Shared utilities — no test_ prefix, never collected
└── fixtures/       Static data files (JSON, YAML, etc.)
```

Component tests live under each tier:

```text
tests/unit/coding_lsp/
tests/integration/coding_lsp/
tests/e2e/coding_lsp/
```

---

## Test tiers

Tiers describe **what is under test**, not how it runs or how fast it is.

| Tier          | What it tests                                      | Key constraint                                     |
| ------------- | -------------------------------------------------- | -------------------------------------------------- |
| `unit`        | A single function or class in isolation            | No real I/O — mock or monkeypatch all boundaries   |
| `integration` | A module or subsystem against real dependencies    | Uses `tmp_path`; may call subprocesses; no network |
| `e2e`         | A complete user-visible workflow end-to-end        | Real CLI, real network, may need Docker            |
| `deferred`    | Code not yet written (placeholder/spec tests)      | Never collected; tracked separately                |
| `dev`         | State of the local checkout (migrations, fixtures) | Never collected in CI                              |

**Tier is orthogonal to execution environment.** An integration test that uses
`tmp_path` runs safely on a developer's laptop. An e2e test that calls `apt-get`
needs Docker. Use markers (below) to express those constraints separately.

---

## Markers

All markers must be declared in `pyproject.toml` under `[tool.pytest.ini_options]`.
`--strict-markers` is enforced — unregistered markers fail collection.

### Marker taxonomy

Markers express **cross-cutting concerns** independently of tier:

#### Execution speed

| Marker | When to apply         | Default CI behaviour             |
| ------ | --------------------- | -------------------------------- |
| `slow` | Single test runs >10s | Included but reported separately |

#### Resource and environment dependencies

| Marker              | When to apply                                    | Gating                                       |
| ------------------- | ------------------------------------------------ | -------------------------------------------- |
| `requires_docker`   | Test needs a Docker daemon (not just isolation)  | Skip unless `DOCKER_AVAILABLE=1`             |
| `mutates_host`      | Test installs/removes packages on the real host  | Always skip locally; runs in CI Docker only  |
| `requires_network`  | Needs outbound internet access                   | Skip unless `NETWORK_TESTS=1`                |
| `requires_uv`       | Needs `uv` on PATH                               | Use `skipif(shutil.which("uv") is None)`     |
| `requires_npm`      | Needs `npm` on PATH                              | Use `skipif(shutil.which("npm") is None)`    |
| `requires_cargo`    | Needs `cargo` on PATH                            | Use `skipif(shutil.which("cargo") is None)`  |
| `requires_gh`       | Needs `gh` CLI on PATH                           | Use `skipif(shutil.which("gh") is None)`     |

#### Behaviour modifiers

| Marker   | When to apply                                            |
| -------- | -------------------------------------------------------- |
| `smoke`  | Minimal sanity check — should pass in every environment  |
| `opt_in` | Destructive or expensive; never run by default           |
| `xfail`  | Known failure; use `strict=True` unless genuinely flaky  |

### Applying markers

```python
import shutil
import pytest

@pytest.mark.slow
@pytest.mark.requires_uv
@pytest.mark.skipif(shutil.which("pyright-langserver") is None, reason="pyright not on PATH")
@pytest.mark.timeout(120)
def test_pyright_completes_full_workspace_check() -> None:
    ...
```

### Auto-applying tier markers via conftest

Apply tier markers automatically from test path so individual tests stay clean:

```python
# tests/conftest.py
def pytest_collection_modifyitems(items):
    for item in items:
        path = item.nodeid.replace("\\", "/")
        if "/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/e2e/" in path:
            item.add_marker(pytest.mark.e2e)
```

This enables `pytest -m integration` without decorating every test function.

### Environment-gated markers — conftest pattern

For tests that must not run outside a controlled environment, gate in the
directory's `conftest.py`, not in each test:

```python
# tests/integration/providers/conftest.py
import os
import pytest

def pytest_collection_modifyitems(config, items):
    if os.environ.get("AUDIAGENTIC_DOCKER_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set AUDIAGENTIC_DOCKER_TESTS=1 to run")
    for item in items:
        if "tests/integration/providers" in item.nodeid.replace("\\", "/"):
            item.add_marker(skip)
```

Use environment variables consistently. Established variables:

| Variable                                | Controls                                         |
| --------------------------------------- | ------------------------------------------------ |
| `AUDIAGENTIC_DOCKER_TESTS=1`            | Lifecycle and provider integration tests         |
| `AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS=1` | Real provider CLI install/uninstall (opt-in)     |
| `NETWORK_TESTS=1`                       | Tests requiring outbound network access          |

---

## Parallel execution and `no_parallel`

The suite runs under `pytest-xdist`. The consolidated runner and CI use
`-n auto --dist loadgroup`, so the whole suite is **one safe command** — you do
not split runs by hand.

Safety comes from an enforcement hook in `tests/conftest.py`:

- A test marked `@pytest.mark.no_parallel` shares a stateful resource (e.g. a
  long-lived LSP subprocess held by a module-scoped fixture).
- The hook finds every **module** containing such a test and pins the *entire
  module* to one `xdist_group`. With `--dist loadgroup` that forces the module
  onto a single worker, where its tests run serially, while the rest of the
  suite still fans out.

So the rule for authors is simply: **mark the test `no_parallel`** — never try
to manage worker placement yourself. Marking one test pins its whole module.

```python
@pytest.mark.no_parallel  # shares the module-scoped LSP connection
def test_lsp_completion_returns_items(...): ...
```

---

## Recipe / mutating test isolation — do NOT collapse

`mutates_host` tests exercise the **real MCP install recipes**: they install a
language server or provider CLI from a clean toolchain, assert it is present and
`detect_missing` is empty, then uninstall and assert it is gone again. The
install/uninstall *is the contract under test*.

Two failure modes silently invalidate these tests — both are banned:

1. **Baking the dependency into the image.** If `pyright` / `clangd` /
   `rust-analyzer` / a provider CLI is pre-installed, the recipe finds it already
   present and the "installed" assertion passes without the recipe doing
   anything. The clean suite image (`Dockerfile.test`) is therefore deliberately
   a **clean toolchain** and runs `-m "not mutates_host"`.

2. **Sharing one container across mutating tests.** One test's installed binary
   leaks into the next test's "assert absent" check. So each mutating scenario
   runs in its **own image / fresh container** (mirrored by
   `tests/dev/run_provider_cli_isolated.py`, which spins a fresh container per
   provider).

Consequence for the image layout: the clean, non-mutating suite is consolidated
into one image, but the mutating recipe images stay separate **on purpose**.
When adding a recipe test, give it an isolated image — never fold it into the
shared suite image, and never bake its dependency into any image a recipe runs in.

---

## Timeouts

Global default: **30 seconds** (`timeout = 30` in `pyproject.toml`).

| Tier / type                    | Typical budget | Action                                    |
| ------------------------------ | -------------- | ----------------------------------------- |
| Unit                           | <1s            | 30s global is a safety net, not a target  |
| Integration (filesystem)       | 5–30s          | Use `@pytest.mark.timeout(N)` if >30s     |
| E2E (fast path)                | 30s            | Override with `@pytest.mark.timeout(N)`   |
| E2E (Docker build + run)       | 300–900s       | Always explicit `@pytest.mark.timeout(N)` |
| Slow compiles (rust-analyzer)  | up to 900s     | Note in test why timeout is high          |

Do not raise the global timeout — override per-test with `@pytest.mark.timeout(N)`.
Never use `time.sleep()` in a unit test.

---

## Naming conventions

### Files

`test_<subject>.py` where subject is the module or behaviour being tested.

### Functions

`test_<what>_<condition>_<expected_outcome>` — or shorter when condition is obvious.

```python
# Good — explicit about what, when, and outcome
def test_detect_missing_returns_only_absent_tools() -> None: ...
def test_apt_install_prepends_update_step() -> None: ...
def test_lsp_config_status_empty_project() -> None: ...
def test_install_propagates_mcp_servers_to_providers() -> None: ...

# Bad — vague or tautological
def test_it_works() -> None: ...
def test_detect_missing_test() -> None: ...
def test_function() -> None: ...
```

### Classes

`Test<Subject>` for grouping related tests under shared setup state. Use only
when multiple tests share expensive `@pytest.fixture(scope="class")` setup —
otherwise prefer plain functions.

---

## Assertions

- One logical assertion per test where possible
- Always use plain `assert` — no custom assertion wrappers
- Include a failure message when the default diff is insufficient

```python
assert result["ok"], f"expected ok=True, got {result}"

assert expected_servers.issubset(present), (
    f"servers {expected_servers - present} missing from {config_path}. "
    f"Present: {present}"
)
```

- Never assert on log output or stdout unless that IS the contract under test
- Never assert on implementation details — assert on public contracts

**Arrange-Act-Assert (AAA) structure** — keep each section visually distinct:

```python
def test_confirm_step_declines_on_no() -> None:
    # Arrange
    step = ConfirmStep(id="confirm", prompt="Proceed?")
    answers = {"confirm": WorkflowAnswer(question_id="confirm", value="no")}

    # Act
    result = step.run({}, answers)

    # Assert
    assert result.status == "skipped"
```

---

## Fixtures

- Declare fixtures in `conftest.py` at the **lowest scope that shares them**
- Root `conftest.py` (`tests/conftest.py`): path setup and global hooks only — no domain logic
- Use `tmp_path` (pytest built-in) for all temp filesystem work — never `os.getcwd()` or hardcoded paths
- Fixture scope default: `function` (strongest isolation); use `session` only for
  expensive read-only shared setup (e.g. a compiled binary or model download)
- Split `conftest.py` into multiple files when it exceeds ~150 lines

---

## Coverage

Target: **80% branch coverage** for `src/`. Current gate: **60%** (ratchet upward as coverage grows).

```bash
pytest --cov=src --cov-branch --cov-report=term-missing --cov-report=html
```

Coverage is a diagnostic, not a goal. 100% coverage on a trivially-mocked module
is worse than 70% on a module with meaningful behaviour tests.

---

## Docker tests

### When Docker is required

| Scenario                                     | Why Docker                                         |
| -------------------------------------------- | -------------------------------------------------- |
| `mutates_host` — installs/removes packages   | Prevent corrupting the developer's local system    |
| Requires specific OS toolchain (apt, brew)   | Reproducible environment across developer machines |
| Full CLI integration (real npm/cargo/uv run) | Match CI environment exactly                       |

**Docker is not required for filesystem isolation.** `tmp_path` provides full
isolation for component lifecycle tests, provider surface tests, and similar
file-based integration tests. Use `tmp_path`; reserve Docker for tests that
genuinely need it.

### Base image

**`audia-test-base`** is the single canonical toolchain image. All test images
`FROM audia-test-base:latest` — never install toolchains from scratch.

| Tool               | Purpose                            |
| ------------------ | ---------------------------------- |
| `python3`, `pip`   | Package install and test execution |
| `node`, `npm`      | JavaScript tooling                 |
| `uv`               | Python tool installs (pyright etc) |
| `cargo`            | Rust tooling (rust-analyzer)       |
| `gh`               | GitHub CLI                         |

### Dockerfile requirements

- `ENV PYTHONDONTWRITEBYTECODE=1` — prevents stale `.pyc` across bind mounts
- `ENV PYTHONUNBUFFERED=1` — immediate stdout flush
- `ENV PYTHONPYCACHEPREFIX=/tmp/pycache` must be set **after** all `RUN` steps.
  Setting it before bakes `.pyc` files into the layer; these fail at runtime with
  `ValueError: bad marshal data` if compile context differed.
- Use `uv` not `pip3` in CMD steps. Debian Bookworm pip has a CPython ABI bug
  (`SystemError: attempting to create PyCFunction with class but no METH_METHOD flag`)
  during wheel resolution on Python 3.11:

  ```bash
  uv venv /venv && uv pip install --python /venv/bin/python -q -e '.[mcp]'
  ```

- Do NOT clean apt lists in component Dockerfiles — the base handles this

### Adding a Docker test

For tests that genuinely require Docker (system packages, real CLI lifecycle):

1. Create `tests/docker/Dockerfile.<component>-<purpose>` extending `audia-test-base:latest`
2. Create in-container test script as a standalone pytest file at
   `tests/integration/<component>/test_<purpose>.py` — this is what the container CMD runs
3. Create host-side pytest test at `tests/e2e/<component>/test_<purpose>_docker.py`
   with `@pytest.mark.docker`, `@pytest.mark.slow`, `@pytest.mark.timeout(N)`,
   `@pytest.mark.mutates_host`
4. Add `build-<component>` and `test-<component>-docker` Make targets

**Container-side scripts** use pytest — not the `section`/`check` pattern.
Pytest output is already structured; duplicating it with a custom format
adds noise and loses assertion detail. Reserve `section`/`check` only for
shell scripts (`*.sh`) that cannot use pytest.

### Full lifecycle coverage for mutates_host tests

Any test that installs a package must also test uninstall. Do not skip uninstall
coverage — broken uninstall leaves orphaned packages on real systems.

1. **Install** — invoke install function, verify binary present, verify `detect_missing` returns `[]`
2. **Uninstall** — invoke uninstall function, verify binary absent, verify `detect_missing` reports dep
3. **Cycle** — reinstall at least one dep, re-verify, uninstall again

For slow compile steps (e.g. `cargo install rust-analyzer` ≈ 10–15 min): install
once and do not cycle — mark with `@pytest.mark.timeout(900)` and add a comment
explaining why cycling is skipped.

### Image layout (collapsed)

The historical per-scenario image sprawl is collapsed only where safe (see
*Recipe / mutating test isolation*):

| Image                              | Dockerfile                          | Purpose                                                    |
| ---------------------------------- | ----------------------------------- | ---------------------------------------------------------- |
| `audia-test-base`                  | `Dockerfile.test-base`              | Shared toolchain base for all suite/recipe images          |
| `audiagentic-test`                 | `Dockerfile.test`                   | **Clean, non-mutating whole suite** (`run_suite.sh`)       |
| `audia-packaging`                  | `Dockerfile.packaging`              | Clean-room wheel: install + server-smoke + release e2e     |
| `audia-provider-cli-test`          | `Dockerfile.provider-cli-test`      | Provider CLI provisioning recipe (isolated)                |
| `audia-provider-cli-comprehensive` | `Dockerfile.provider-cli-comprehensive` | Provider CLI comprehensive recipe (isolated)          |
| `audiagentic-provider-lifecycle-e2e` | `Dockerfile.provider-lifecycle-e2e` | Provider full lifecycle recipe (isolated)               |
| `audia-provider-lsp-e2e`           | `Dockerfile.provider-lsp-e2e`       | Provider LSP install recipe (isolated)                     |
| `audia-mcp-tools-e2e`              | `Dockerfile.mcp-tools-e2e`          | LSP MCP tools — *consumes* pre-baked servers (isolated)    |
| `audiagentic-lsp-install-test`     | `Dockerfile.lsp-install-test`       | Clean LSP install recipe; slow rust compile (~15 min)      |

The former `install-test`, `release-test` and `server-smoke` images merged into
`audia-packaging`; `shell-stdout-test` folded into the clean suite image.

### Build once, run many

```bash
make build-base             # Build audia-test-base (once, or on Dockerfile.test-base change)
make build-lsp-install      # Build LSP install test image
make test-lsp-docker        # Run LSP install recipe in docker
make test-docker            # Run the clean non-mutating suite in docker
make test-packaging-docker  # Run clean-room wheel/install/server checks
```

---

## CI execution matrix

| Command / target                       | Markers included      | Markers excluded         | Environment vars required    |
| -------------------------------------- | --------------------- | ------------------------ | ---------------------------- |
| `make test-all`                        | host suite + docker (if daemon) | `opt_in`       | auto                         |
| `make test-fast`                       | host suite only       | `docker`, `mutates_host` | —                            |
| `make test-unit`                       | `unit`                | —                        | —                            |
| `make test`                            | `unit`, `integration` | `mutates_host`, `opt_in` | —                            |
| `make test-docker`                     | clean non-mutating suite | `mutates_host`, `opt_in` | runs inside Docker        |
| `make test-packaging-docker`           | clean-room wheel/install/server | —                | runs inside Docker           |
| `make test-lsp-docker`                 | LSP install recipe    | —                        | runs inside Docker           |
| `pytest -m smoke`                      | `smoke`               | —                        | —                            |
| `pytest -m 'not slow'`                 | all except `slow`     | —                        | —                            |

`make test-all` (→ `python tests/run_all.py`) is the single front door: it runs
the whole host suite in parallel and, when a Docker daemon is reachable, builds
the image set once and runs the in-container suites (mutating recipe images each
in their own fresh container). In CI the `tests` + `docker-tests` jobs cover the
same ground as a parallel matrix.

---

## What NOT to test

- Framework internals (FastMCP dispatch, asyncio event loop, pytest itself)
- Third-party library correctness (`yaml.safe_load`, `shutil.which`, `json.loads`)
- Trivial attribute access on dataclasses with no logic
- Implementation details that can change without breaking the public contract
- Logging output or stdout unless that is the observable contract

---

## Running tests

```bash
# Everything appropriate to this machine, one command:
#   host suite in parallel, + docker suites if a daemon is reachable
make test-all                 # or: python tests/run_all.py
python tests/run_all.py --fast       # host only, never touch docker
python tests/run_all.py --lsp-install # also the slow (~15 min) LSP install image

# Fast feedback — unit only
make test-unit

# Standard local run — unit + integration (no mutates_host)
make test

# Include gated integration tests (safe, filesystem-isolated)
AUDIAGENTIC_DOCKER_TESTS=1 make test

# Skip slow tests
pytest -m 'not slow'

# Smoke pass — minimal sanity in any environment
pytest -m smoke

# With branch coverage report
pytest --cov=src --cov-branch --cov-report=term-missing

# Docker LSP install (~10 min; includes rust-analyzer)
make test-lsp-docker

# Full Docker suite (authoritative)
make test-docker
```
