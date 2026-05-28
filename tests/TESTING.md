# Testing Standards

Covers: folder structure, test categories, markers, naming, assertions, fixtures,
timeouts, coverage, and Docker test conventions.

## Folder structure

```text
tests/
├── unit/           Pure Python — no subprocess, no filesystem side effects, no network
├── integration/    Real I/O: filesystem, subprocess, local ports; no Docker
├── e2e/            Full stack: real CLI, may spawn Docker; always runs in CI Docker
├── deferred/       Tests for planned / not-yet-built modules; never collected in CI
├── dev/            Developer-only: local checkout state; never collected in CI
├── helpers/        Shared test utilities (no test_ prefix, not collected)
└── fixtures/       Static data files
```

Component tests live under each tier:

```text
tests/unit/coding_lsp/
tests/integration/coding_lsp/
tests/e2e/coding_lsp/
```

## Test categories

| Tier          | Rules                                                    | Examples                               |
| ------------- | -------------------------------------------------------- | -------------------------------------- |
| `unit`        | No subprocess, no real filesystem writes, no network     | Parser, config reader, recipe builder  |
| `integration` | May use real filesystem (`tmp_path`), real subprocess    | LSP bridge with real server binary     |
| `e2e`         | Full user-facing path; real CLI or Docker                | `audiagentic install`, Docker recipe   |
| `deferred`    | Module or feature doesn't exist yet                      | Tests for `audiagentic.execution.jobs` |

## Markers

All markers must be registered in `pyproject.toml`. `--strict-markers` is enforced —
unregistered markers are an error, not a warning.

| Marker            | Apply when                    | Effect                                   |
| ----------------- | ----------------------------- | ---------------------------------------- |
| `slow`            | Test runs >10s                | Excludable: `pytest -m 'not slow'`       |
| `docker`          | Test needs Docker daemon      | Excludable: `pytest -m 'not docker'`     |
| `requires_network`| Needs outbound internet       | Note for CI/offline environments         |
| `requires_uv`     | Needs `uv` on PATH            | Pair with `pytest.mark.skipif`           |
| `requires_npm`    | Needs `npm` on PATH           | Pair with `pytest.mark.skipif`           |
| `requires_cargo`  | Needs `cargo` on PATH         | Pair with `pytest.mark.skipif`           |

Use `pytest.mark.skipif` to guard tests that need binaries:

```python
import shutil
import pytest

@pytest.mark.slow
@pytest.mark.requires_uv
@pytest.mark.skipif(shutil.which("pyright-langserver") is None, reason="pyright not on PATH")
@pytest.mark.timeout(60)
def test_pyright_initializes() -> None:
    ...
```

Use `@pytest.mark.timeout(N)` on individual tests that legitimately exceed the 30s default.
Do not raise the global timeout — fix the test instead.

## Timeouts

Global default: **30 seconds** (set in `pyproject.toml` via `pytest-timeout`).

| Tier              | Typical timeout                                    |
| ----------------- | -------------------------------------------------- |
| Unit              | <1s (30s global is generous safety net)            |
| Integration       | 5–30s                                              |
| E2E (fast)        | 30s                                                |
| E2E (docker run)  | 300–900s — use `@pytest.mark.timeout(N)`           |

Never call `time.sleep()` in a unit test. Use mocks or real async coordination instead.

## Coverage

Target: **80% branch coverage** for `src/`. Current gate: **60%** (ratchet upward).

Run with:

```bash
pytest --cov=src --cov-branch --cov-report=term-missing --cov-report=html
```

Coverage is a diagnostic, not a goal. 100% coverage on a trivially-tested module is worse
than 70% on a well-designed one.

## Naming conventions

- Files: `test_<subject>.py` where subject is the module or behaviour
- Functions: `test_<what>_<condition>_<expected>` or `test_<what>` when condition is obvious
- Classes: `Test<Subject>` for grouping related tests under shared state

```python
# Good
def test_detect_missing_returns_only_absent_tools() -> None: ...
def test_apt_install_prepends_update_step() -> None: ...
def test_lsp_config_status_empty_project() -> None: ...

# Bad
def test_it_works() -> None: ...
def test_detect_missing_test() -> None: ...
```

## Assertions

- One logical assertion per test where possible
- Always use plain `assert` — no custom wrappers
- Include a failure message when the default diff is insufficient:

  ```python
  assert result["ok"], f"expected ok=True, got {result}"
  ```

- Never assert on log output or stdout unless that IS the contract under test

Use **Arrange-Act-Assert** structure:

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

## Fixtures

- Place fixtures in `conftest.py` at the **lowest scope that uses them**
- Root `conftest.py` (`tests/conftest.py`): path/env setup only — no component logic
- Use `tmp_path` (pytest built-in) for temp filesystem — never `os.getcwd()` or hardcoded paths
- Scope: default `function`; use `session` only for expensive read-only shared setup
- Split `conftest.py` when it exceeds ~150 lines

## Docker tests

### Base image

**`audia-test-base`** is the single canonical toolchain image. All Docker test images
must extend it — never install toolchains from scratch in a component Dockerfile.

| Tool             | Purpose                            |
| ---------------- | ---------------------------------- |
| `python3`, `pip` | Package install and test execution |
| `node`, `npm`    | JavaScript tooling                 |
| `uv`             | Python tool installs (pyright)     |
| `cargo`          | Rust tooling (rust-analyzer)       |
| `brew`           | Homebrew packages                  |
| `gh`             | GitHub CLI                         |

### Image requirements

- `ENV PYTHONDONTWRITEBYTECODE=1` — prevents stale `.pyc` across bind mounts
- `ENV PYTHONUNBUFFERED=1` — immediate stdout flush
- `ENV PYTHONPYCACHEPREFIX=/tmp/pycache` must be set **after** all `RUN` steps in the base
  image, not before. Setting it before causes build-time `.pyc` files to be baked into
  `/tmp/pycache` inside the image layer; these are then read at runtime and fail with
  `ValueError: bad marshal data` if the compile context differed.
- Do NOT use `pip3 install` or system pip in container CMDs. Debian Bookworm's Python 3.11
  pip has a CPython ABI bug (`SystemError: attempting to create PyCFunction with class but
  no METH_METHOD flag`) that fires during wheel resolution. Use `uv` instead:

  ```bash
  uv venv /venv && uv pip install --python /venv/bin/python -q -e '.[mcp]' && /venv/bin/python script.py
  ```

- Do NOT clean apt lists in component Dockerfiles — the base handles this

### System-impacting functions — Docker gate

Any test that performs a real install, uninstall, or package-manager operation on the
host **must** run inside Docker. This prevents corrupting the developer's local environment.

Functions that require Docker gate:

| Function                       | Package manager  | Docker test location          |
| ------------------------------ | ---------------- | ----------------------------- |
| `install_dependencies` (LSP)   | uv/npm/cargo/apt | `test_install_deps.py`        |
| `uninstall_dependencies` (LSP) | uv/npm/cargo/apt | same                          |
| `install_system_dependencies`  | varies           | same (system dep section)     |
| `PlatformRecipe.run()`         | apt on Linux     | same (PlatformRecipe section) |

The container-side test script must cover the full lifecycle:

1. **Install** — invoke `install_dependencies`, verify binary on PATH, check `detect_missing` returns `[]`
2. **Uninstall** — invoke `uninstall_dependencies`, verify binary absent, check `detect_missing` reports the dep
3. **Cycle** — reinstall at least one dep, re-verify, uninstall again

Do NOT skip uninstall coverage just because a dep was installed. Broken uninstall leaves
orphaned packages on real systems.

For slow compile steps (e.g. `cargo install rust-analyzer` ≈ 10–15 min), install once and
do not cycle — note this explicitly in a comment in the script.

### Build once, run many

```bash
make build-base           # Build audia-test-base (run once or on Dockerfile.test-base change)
make build-lsp-install    # Build LSP install test image
make test-lsp-docker      # Run LSP install test (no rebuild, bind-mount source)
make test-docker          # Run full suite in Docker
```

### Adding a Docker test

1. Create `Dockerfile.<component>-<purpose>` at repo root
2. `FROM audia-test-base:latest`
3. Add `build-<component>` and `test-<component>-docker` to `Makefile`
4. Add host-side pytest test in `tests/e2e/<component>/test_<purpose>_docker.py`
   with `@pytest.mark.docker`, `@pytest.mark.slow`, `@pytest.mark.timeout(N)`
5. Create a standalone script in `tests/integration/<component>/test_<purpose>.py`
   that runs inside the container (what the CMD calls)

### Docker test script output format

Use the section/check pattern for container-side scripts:

```python
FAILURES: list[str] = []

def check(label: str, condition: bool) -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        FAILURES.append(label)

def section(title: str) -> None:
    print(f"\n=== {title} ===")

# ... test body ...

if FAILURES:
    print(f"\nFAILED: {FAILURES}")
    sys.exit(1)
print("\nAll checks passed.")
```

## What NOT to test

- Framework internals (FastMCP dispatch, asyncio scheduling, pytest itself)
- Third-party library correctness (yaml.safe_load, shutil.which)
- Trivial getters on dataclasses with no logic
- Implementation details that can change without breaking the public contract

## Running tests

```bash
# Standard: unit + integration + e2e
make test

# Unit only (fast, no network, no Docker)
make test-unit

# Skip slow tests
pytest -m 'not slow'

# Only slow tests
pytest -m slow

# With coverage report
pytest --cov=src --cov-branch --cov-report=term-missing

# Docker LSP install (all 4 servers, takes ~10 min for rust-analyzer)
make test-lsp-docker

# Full Docker suite
make test-docker
```
