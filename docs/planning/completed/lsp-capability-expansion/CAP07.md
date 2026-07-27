---
id: CAP07
order: 7
plan: lsp-capability-expansion
state: done
validate-first: true
priority: P2
work: S
---

# Install recipes for added tools

## Description

Every tool a language needs to deliver its now-exposed capabilities must appear in
that language's install recipe. Primary add: ruff for Python (covered by the new
`python-ruff.yaml` from CAP03). Secondary: audit each other language's recipe to
confirm no capability silently needs an unlisted binary.

All install recipe changes are env-mutating. Validate in the Docker harness.
Do not gate-override on the host machine.

**Prerequisites:** CAP03 (ruff YAML exists), CAP06 (matrix reveals any gaps).

---

## Exact implementation steps (sequential)

### Step 1 — Verify ruff recipe round-trips through the dependency system

The ruff install recipe lives in `src/audiagentic/config/components/coding-lsp/python-ruff.yaml`
(created in CAP03). Before any other work, confirm the registry reads it correctly.

Run:

```
pytest tests/unit/coding_lsp/test_language_registry.py -x -q
```

Then verify in a Python shell or a dedicated test that the recipe round-trips:

```python
from audiagentic.components.coding_lsp import language_registry

cfgs = language_registry.dependency_cfgs(["python-ruff"])
assert "ruff" in cfgs
cfg = cfgs["ruff"]
assert cfg.get("probe") == "binary:ruff"
assert cfg.get("toolchain") == "uv"
assert cfg.get("package") == "ruff"
assert cfg.get("uninstall-package") == "ruff"

ids = language_registry.dependency_ids(["python-ruff"])
assert "ruff" in ids
```

If this fails, the YAML is malformed or the `language_spec_from_data` parser does
not support the `requires.min-version` field yet. Check `language_registry.py` lines
89-101. The `dep_raw` dict is built from the `dependencies` block; `requires` is
stored inside `dep_cfg` and passed through opaquely, so it should not break parsing.

---

### Step 2 — Confirm ruff install/status commands surface the new dependency

**File:** `src/audiagentic/components/coding_lsp/coding_lsp_config.py`

The `discover_language_servers` function (updated in CAP01) iterates
`resolve_active_runtime_servers` and calls `build_dependency_probes` for each
language's dependency. After CAP01 + CAP03, Python has two entries:
`python` (pyright) and `python-ruff` (ruff). Both should appear in status output
when both features are enabled.

Manually verify:

```
ag component coding-lsp status
```

Expected output includes both `pyright` and `ruff` with their probe results when
`python-ruff` is enabled for the project.

If the component command only iterates one server per language, find where it calls
`dependency_ids` / `dependency_cfgs` and update to pass both `["python", "python-ruff"]`
when Python is the configured language.

---

### Step 3 — Audit Python install recipe (pyright — unchanged)

`src/audiagentic/config/components/coding-lsp/python.yaml` (pyright)

Current recipe:

```yaml
dependencies:
  pyright:
    display-name: Pyright (Python LSP)
    probe: binary:pyright-langserver
    toolchain: uv
    package: pyright
```

No change needed. Pyright's `pyright-langserver` binary is what the probe checks.
`pyright` package (via uv) installs both the CLI and the langserver. Confirmed.

---

### Step 4 — Audit Rust install recipe

**File:** `src/audiagentic/config/components/coding-lsp/rust.yaml`

Current recipe:

```yaml
dependencies:
  rust-analyzer:
    display-name: Rust Analyzer
    probe: command:rust-analyzer --version
    toolchain: rustup
    package: rust-analyzer
```

Rust-analyzer via rustup also provides rustfmt and clippy (via the `rust-src` and
`rust-analysis` rustup components). These are needed for:

- `textDocument/formatting` → rust-analyzer calls rustfmt internally
- `textDocument/codeAction` → clippy-based code actions

Check whether `rustup component add rust-src rust-analysis` is required separately
or if the `rust-analyzer` package pulls them in. On standard toolchain installs,
`rust-analyzer` via `rustup component add rust-analyzer` is sufficient and rustfmt
ships with the standard toolchain.

**Decision:** No change to `rust.yaml`. Add a comment noting that rustfmt is part
of the standard Rust toolchain and does not need a separate recipe entry.

If formatting returns empty edits despite `documentFormattingProvider: true`,
the issue is `rustfmt` not on PATH. Add a probe check to the recipe:

```yaml
dependencies:
  rust-analyzer:
    display-name: Rust Analyzer
    probe: all-binaries:rust-analyzer,rustfmt
    toolchain: rustup
    package: rust-analyzer
```

The `all-binaries` probe format (if supported by the foundation probe system) checks
both binaries. If the probe format is not supported, document it in the component
notes rather than adding a separate recipe entry.

---

### Step 5 — Audit C/C++ install recipe

**File:** `src/audiagentic/config/components/coding-lsp/cpp.yaml`

Current recipe:

```yaml
dependencies:
  clangd:
    display-name: Clangd (C/C++ LSP)
    probe: binary:clangd
    via:
      winget: LLVM.LLVM
      scoop: clangd
      choco: llvm
      brew: clangd
      apt: clangd
      dnf: clangd
      pacman: clangd
```

Clangd bundles clang-format and clang-tidy in the same LLVM package, so:

- `textDocument/formatting` → clangd invokes `clang-format` (same package)
- `textDocument/codeAction` → clang-tidy code actions (same package)
- `textDocument/inlayHint` → built into clangd

No additional recipe entry needed. The single `clangd` probe is sufficient because
all tools ship with LLVM.

**No change to `cpp.yaml`.**

---

### Step 6 — Audit TypeScript install recipe

**File:** `src/audiagentic/config/components/coding-lsp/typescript.yaml`

Current recipe:

```yaml
dependencies:
  typescript-language-server:
    display-name: TypeScript Language Server
    probe: all-binaries:typescript-language-server,tsserver
    toolchain: npm
    package: [typescript-language-server, typescript]
    uninstall-package: [typescript-language-server, typescript]
```

TypeScript formatting via `typescript-language-server` uses the TypeScript compiler's
built-in formatter. No companion tool is needed. Prettier/ESLint are common but
project-configured and out of scope for the component install recipe.

**Decision on ESLint/Biome:** Out of scope for now. These are project-level dev
dependencies, not component-level server dependencies. Document this in the notes.

**No change to `typescript.yaml`.**

---

### Step 7 — Add language recipe coverage to the test suite

**File:** `tests/unit/coding_lsp/test_language_registry.py`

Add tests to confirm that every configured language has a valid dependency recipe
and that the recipe contains the minimum required fields:

```python
import pytest
from audiagentic.components.coding_lsp import language_registry


@pytest.mark.parametrize("language_id", [
    "python", "python-ruff", "typescript", "rust", "cpp",
])
def test_language_has_dependency_cfg(language_id: str) -> None:
    """Every language must have a dependency recipe for install/status."""
    cfgs = language_registry.dependency_cfgs([language_id])
    assert cfgs, f"{language_id}: expected at least one dependency cfg"
    for dep_id, cfg in cfgs.items():
        assert "probe" in cfg, f"{language_id}/{dep_id}: missing probe field"


@pytest.mark.parametrize("language_id", [
    "python", "python-ruff", "typescript", "rust", "cpp",
])
def test_language_dependency_id_non_empty(language_id: str) -> None:
    ids = language_registry.dependency_ids([language_id])
    assert ids, f"{language_id}: expected at least one dependency id"
    for dep_id in ids:
        assert dep_id, f"{language_id}: dependency id must not be empty string"


def test_ruff_dep_has_uv_toolchain() -> None:
    cfgs = language_registry.dependency_cfgs(["python-ruff"])
    assert cfgs.get("ruff", {}).get("toolchain") == "uv"


def test_ruff_dep_has_correct_probe() -> None:
    cfgs = language_registry.dependency_cfgs(["python-ruff"])
    assert cfgs.get("ruff", {}).get("probe") == "binary:ruff"
```

---

### Step 8 — Update component documentation

**File:** Find the coding-lsp component doc (check `docs/` for a markdown file
describing the coding-lsp component, or the component descriptor itself).

Add or update a "Per-language tool matrix" section:

```
## Per-language tool matrix

| Language | Servers | Formatting | Lint diags | Type diags | Workspace pull |
|----------|---------|-----------|-----------|-----------|---------------|
| Python   | pyright + ruff | ruff | ruff (E/F/I/UP) | pyright | ruff (workspace) |
| TypeScript | typescript-language-server | ts built-in | ts built-in | ts built-in | no (push only) |
| Rust | rust-analyzer | rustfmt (via ra) | clippy (via ra) | ra | no (push only) |
| C/C++ | clangd | clang-format (via clangd) | clang-tidy (via clangd) | clangd | no (push only) |

## mutation-enabled setting

Default: `false`. When `true`, the `lsp_apply_*` tools become available in the MCP
surface and `lsp_capabilities` reports mutation methods. Set per project in
`.audiagentic/state/components/coding-lsp.json` or via `ag component coding-lsp set
mutation-enabled true`.

## Install

- Python: `ag component coding-lsp install python` installs pyright (uv).
  `ag component coding-lsp install python-ruff` installs ruff (uv). Both required
  for full Python capability.
- TypeScript: `ag component coding-lsp install typescript` installs
  typescript-language-server + typescript (npm).
- Rust: `ag component coding-lsp install rust` adds rust-analyzer (rustup).
- C/C++: `ag component coding-lsp install cpp` installs clangd (platform package manager).
```

---

## Files

| File | Change |
|------|--------|
| `src/audiagentic/config/components/coding-lsp/python-ruff.yaml` | Created in CAP03 — verify round-trip here |
| `src/audiagentic/config/components/coding-lsp/rust.yaml` | No change (optionally add `all-binaries` probe) |
| `src/audiagentic/config/components/coding-lsp/cpp.yaml` | No change |
| `src/audiagentic/config/components/coding-lsp/typescript.yaml` | No change |
| `tests/unit/coding_lsp/test_language_registry.py` | Add 5 parametrized recipe tests |
| Component doc (markdown) | Add per-language tool matrix + mutation-enabled notes |

## Validation

```
pytest tests/unit/coding_lsp/test_language_registry.py -x -q
```

All parametrized recipe tests pass (pyright, ruff, typescript, rust, cpp each have
a valid dep id with a probe field). Install command provisions ruff + pyright for
Python; status reports both. Uninstall removes what install added.

Validate install/uninstall in the Docker harness (never on the host — it mutates
the environment):

```
docker build -t ag-test .
docker run --rm ag-test pytest tests/integration/ -x -q
```

## Effort & Risk

Simple. Config and test additions only. Risk is forgetting a companion binary a
capability silently needs — the CAP06 matrix surfaces that as an unsupported
result in the integration tier. The unit recipe tests in this item catch missing
dep-cfg entries before the integration tier runs.

## Dependencies

CAP03 (ruff feature YAML), CAP06 (matrix reveals missing backing tools).

## Notes

- ESLint and Biome are explicitly out of scope. They are project-configured dev
  dependencies, not component-level server companions.
- The `requires.min-version` field in `python-ruff.yaml` is documentation only
  unless the foundation probe system supports version floor checks. If it does not,
  consider adding a probe using `command:ruff --version` with a minimum check.
- ruff's `--preview` flag in the server command enables experimental rules.
  Projects can override `server-settings` in their feature state to disable it.
- Install recipe changes are env-mutating: always validate in the Docker image.
  The project policy `feedback_no_local_docker_tests.md` applies here.
