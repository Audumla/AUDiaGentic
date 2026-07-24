---
id: CAP06
order: 6
plan: plan-lsp-capability-expansion
state: done
validate-first: true
priority: P1
work: M
---

# Per-language capability matrix tests

## Description

The guardrail against the original silent-failure class: advertised capability vs
actually delivered result. Catches bugs like the original `workspace.diagnostic`
path error (wrong key → `has_capability` always returned False) and the push-only
server receiving a workspace pull request (30 s hang).

Two tiers:

- **Unit matrix** — fast, no binaries needed. Drives `has_capability` and each
  tool's gate against a recorded capability set fixture. Asserts the path taken
  (pull vs push vs CLI) matches what the capability set advertises.

- **Integration matrix** — gated, real binaries, runs in Docker harness only.
  Seeds a file with a known error, runs each tool, asserts real data or correct
  `unsupported` — never a hang or crash.

**Prerequisites:** CAP01–CAP05 must be complete — tests assert their combined behavior.

---

## Exact implementation steps (sequential)

### Step 1 — Create capability fixtures

**File:** `tests/unit/coding_lsp/fixtures/capability_sets.py` (new file)

These dicts are representative `ServerCapabilities` objects that would be returned
by real servers during `initialize`. They are used as the `session._capabilities`
value in unit tests.

```python
"""Recorded capability sets for per-language matrix tests.

Each dict is a representative ServerCapabilities object for a real server.
Used to drive has_capability() and diagnostics-path-selection tests without
requiring any server binary.
"""
from __future__ import annotations
from typing import Any

# pyright-langserver (push-only, no diagnosticProvider.workspaceDiagnostics)
PYRIGHT: dict[str, Any] = {
    "definitionProvider": True,
    "hoverProvider": True,
    "referencesProvider": True,
    "documentSymbolProvider": True,
    "workspaceSymbolProvider": True,
    "typeDefinitionProvider": True,
    "implementationProvider": True,
    "renameProvider": True,
    "codeActionProvider": True,
    "completionProvider": {"resolveProvider": True, "triggerCharacters": ["."]},
    "signatureHelpProvider": {"triggerCharacters": ["(", ","]},
    "documentFormattingProvider": False,   # pyright does not format
    "inlayHintProvider": True,
    "callHierarchyProvider": True,
    "diagnosticProvider": {
        "identifier": "pyright",
        "interFileDependencies": True,
        "workspaceDiagnostics": False,     # push-only for workspace
    },
}

# ruff server (pull-capable, lint + format, no navigation)
RUFF: dict[str, Any] = {
    "documentFormattingProvider": True,
    "codeActionProvider": {
        "codeActionKinds": ["quickfix", "source.organizeImports"],
    },
    "diagnosticProvider": {
        "identifier": "ruff",
        "interFileDependencies": False,
        "workspaceDiagnostics": True,      # supports workspace pull
    },
    # ruff does NOT provide navigation
    "definitionProvider": False,
    "hoverProvider": False,
    "referencesProvider": False,
    "renameProvider": False,
    "completionProvider": False,
    "signatureHelpProvider": False,
    "inlayHintProvider": False,
}

# typescript-language-server
TYPESCRIPT: dict[str, Any] = {
    "definitionProvider": True,
    "hoverProvider": True,
    "referencesProvider": True,
    "documentSymbolProvider": True,
    "workspaceSymbolProvider": True,
    "typeDefinitionProvider": True,
    "implementationProvider": True,
    "renameProvider": True,
    "codeActionProvider": True,
    "completionProvider": {"resolveProvider": True, "triggerCharacters": [".", '"', "'"]},
    "signatureHelpProvider": {"triggerCharacters": ["(", ",", "<"]},
    "documentFormattingProvider": True,
    "documentRangeFormattingProvider": True,
    "inlayHintProvider": True,
    "callHierarchyProvider": True,
    "typeHierarchyProvider": True,
    # push-only: no diagnosticProvider
}

# rust-analyzer
RUST_ANALYZER: dict[str, Any] = {
    "definitionProvider": True,
    "hoverProvider": True,
    "referencesProvider": True,
    "documentSymbolProvider": True,
    "workspaceSymbolProvider": True,
    "typeDefinitionProvider": True,
    "implementationProvider": True,
    "renameProvider": True,
    "codeActionProvider": True,
    "completionProvider": {"resolveProvider": True, "triggerCharacters": ["::", "."]},
    "signatureHelpProvider": {"triggerCharacters": ["(", ","]},
    "documentFormattingProvider": True,
    "inlayHintProvider": True,
    "callHierarchyProvider": True,
    "typeHierarchyProvider": True,
    # push-only: no diagnosticProvider
}

# clangd (C/C++)
CLANGD: dict[str, Any] = {
    "definitionProvider": True,
    "hoverProvider": True,
    "referencesProvider": True,
    "documentSymbolProvider": True,
    "workspaceSymbolProvider": True,
    "typeDefinitionProvider": True,
    "implementationProvider": True,
    "renameProvider": True,
    "codeActionProvider": True,
    "completionProvider": {"resolveProvider": True, "triggerCharacters": [".", "->", "::"]},
    "signatureHelpProvider": {"triggerCharacters": ["(", ","]},
    "documentFormattingProvider": True,
    "inlayHintProvider": True,
    "callHierarchyProvider": True,
    "typeHierarchyProvider": True,
    # push-only: no diagnosticProvider
}
```

---

### Step 2 — Create unit capability matrix test file

**File:** `tests/unit/coding_lsp/test_capability_matrix.py` (new file)

```python
"""Per-language capability matrix tests.

Asserts that has_capability() correctly reads the *Provider keys for every
method the surface exposes, for every configured server's recorded capability
set. Catches map-key bugs (e.g. the old textDocument.definition path) before
any binary is needed.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from audiagentic.components.coding_lsp.lsp_lifecycle import LspSession, ServerConfig
from tests.unit.coding_lsp.fixtures.capability_sets import (
    CLANGD, PYRIGHT, RUFF, RUST_ANALYZER, TYPESCRIPT,
)


def _session(caps: dict) -> LspSession:
    cfg = ServerConfig(command=["mock"], file_extensions=[".x"], server_id="mock")
    s = LspSession(cfg, "/tmp")
    s._capabilities = caps
    s.bridge = MagicMock()
    return s


# ---------------------------------------------------------------------------
# Method → provider-key correctness (one test per method, all servers)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caps,method,expected", [
    # definition
    (PYRIGHT, "textDocument/definition", True),
    (RUFF, "textDocument/definition", False),
    (TYPESCRIPT, "textDocument/definition", True),
    (RUST_ANALYZER, "textDocument/definition", True),
    (CLANGD, "textDocument/definition", True),
    # hover
    (PYRIGHT, "textDocument/hover", True),
    (RUFF, "textDocument/hover", False),
    (TYPESCRIPT, "textDocument/hover", True),
    # formatting
    (PYRIGHT, "textDocument/formatting", False),
    (RUFF, "textDocument/formatting", True),
    (TYPESCRIPT, "textDocument/formatting", True),
    (RUST_ANALYZER, "textDocument/formatting", True),
    # inlay hints
    (PYRIGHT, "textDocument/inlayHint", True),
    (RUFF, "textDocument/inlayHint", False),
    (TYPESCRIPT, "textDocument/inlayHint", True),
    # signature help
    (PYRIGHT, "textDocument/signatureHelp", True),
    (RUFF, "textDocument/signatureHelp", False),
    # type hierarchy
    (PYRIGHT, "textDocument/typeHierarchy", False),
    (TYPESCRIPT, "textDocument/typeHierarchy", True),
    (RUST_ANALYZER, "textDocument/typeHierarchy", True),
    (CLANGD, "textDocument/typeHierarchy", True),
    # completion
    (PYRIGHT, "textDocument/completion", True),
    (RUFF, "textDocument/completion", False),
    # workspace diagnostics pull
    (PYRIGHT, "workspace/diagnostic", False),
    (RUFF, "workspace/diagnostic", True),
    (TYPESCRIPT, "workspace/diagnostic", False),
    # code actions
    (PYRIGHT, "textDocument/codeAction", True),
    (RUFF, "textDocument/codeAction", True),
    (TYPESCRIPT, "textDocument/codeAction", True),
    # rename
    (PYRIGHT, "textDocument/rename", True),
    (RUFF, "textDocument/rename", False),
])
def test_has_capability_matrix(caps: dict, method: str, expected: bool) -> None:
    session = _session(caps)
    result = session.has_capability(method)
    assert result == expected, (
        f"has_capability({method!r}) = {result}, expected {expected}\n"
        f"caps keys: {list(caps.keys())}"
    )


# ---------------------------------------------------------------------------
# Diagnostics path selection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caps,expected_path", [
    (PYRIGHT, "cli"),         # no workspaceDiagnostics → CLI fallback
    (RUFF, "lsp_pull"),       # workspaceDiagnostics: true → workspace pull
    (TYPESCRIPT, "cli"),      # no diagnosticProvider at all → CLI (then fails fast EXT-LSP-004)
    (RUST_ANALYZER, "cli"),
    (CLANGD, "cli"),
])
def test_workspace_diagnostics_path_selection(caps: dict, expected_path: str) -> None:
    """Assert the code path chosen by diagnostics() matches capability advertisement."""
    session = _session(caps)
    assert session._supports_workspace_diagnostic() == (expected_path == "lsp_pull"), (
        f"Expected _supports_workspace_diagnostic()={expected_path == 'lsp_pull'} "
        f"for caps={list(caps.keys())}"
    )


@pytest.mark.parametrize("caps,expected_pull", [
    (PYRIGHT, True),    # pyright advertises diagnosticProvider (doc pull, workspace: false)
    (RUFF, True),       # ruff advertises diagnosticProvider with workspace: true
    (TYPESCRIPT, False),  # no diagnosticProvider
    (RUST_ANALYZER, False),
    (CLANGD, False),
])
def test_document_diagnostic_path_selection(caps: dict, expected_pull: bool) -> None:
    """Assert file_diagnostics would use pull vs push based on advertised capability."""
    session = _session(caps)
    assert session._supports_document_diagnostic() == expected_pull


# ---------------------------------------------------------------------------
# Tool gates: capability-gated methods return empty/None when unsupported
# ---------------------------------------------------------------------------

def test_inlay_hints_gate_ruff() -> None:
    """ruff does not support inlay hints — must return [] not hang."""
    session = _session(RUFF)
    result = session.inlay_hints("file:///f.py", 0, 0, 10, 0)
    assert result == []
    session.bridge.send_request.assert_not_called()


def test_signature_help_gate_ruff() -> None:
    session = _session(RUFF)
    result = session.signature_help("file:///f.py", 5, 10)
    assert result is None
    session.bridge.send_request.assert_not_called()


def test_type_hierarchy_gate_pyright() -> None:
    """pyright has no typeHierarchyProvider — must return [] not hang."""
    session = _session(PYRIGHT)
    result = session.type_hierarchy_prepare("file:///f.py", 5, 10)
    assert result == []
    session.bridge.send_request.assert_not_called()


def test_completion_gate_ruff() -> None:
    session = _session(RUFF)
    result = session.completion("file:///f.py", 5, 10)
    assert result == []
    session.bridge.send_request.assert_not_called()


def test_formatting_gate_pyright() -> None:
    """pyright does not format — must return [] not hang."""
    session = _session(PYRIGHT)
    result = session.formatting("file:///f.py")
    assert result == []
    session.bridge.send_request.assert_not_called()


def test_definition_gate_ruff() -> None:
    """ruff has no definitionProvider."""
    session = _session(RUFF)
    result = session.definition("file:///f.py", 5, 10)
    # definition() has no capability gate — it just sends the request.
    # has_capability should return False so routing skips this server.
    assert not session.has_capability("textDocument/definition")


# ---------------------------------------------------------------------------
# Mutation capability mirroring (CAP05)
# ---------------------------------------------------------------------------

def test_mutation_methods_excluded_from_capability_label_set() -> None:
    """When mutation is disabled, formatting/rename/codeAction absent from lsp_capabilities."""
    from unittest.mock import patch
    from audiagentic.components.coding_lsp import lsp_api
    from audiagentic.components.coding_lsp.lsp_lifecycle import ServerConfig

    cfg = ServerConfig(command=["m"], file_extensions=[".py"], server_id="pyright")
    mock_session = MagicMock()
    mock_session.capabilities.return_value = PYRIGHT
    mock_session.has_capability.side_effect = lambda m: _session(PYRIGHT).has_capability(m)

    with patch("audiagentic.components.coding_lsp.lsp_api._resolve_language_servers_for_file",
               return_value=[("python", cfg)]):
        with patch("audiagentic.components.coding_lsp.lsp_api._session_manager") as mock_mgr:
            with patch("audiagentic.components.coding_lsp.lsp_api.mutation_enabled", return_value=False):
                mock_mgr.get_or_create.return_value = mock_session
                result = lsp_api.server_capabilities("src/foo.py")

    assert "rename" not in result["supported"]
    assert "codeAction" not in result["supported"]
    assert result["mutation_enabled"] is False
    assert "definition" in result["supported"]  # read-only still present
```

---

### Step 3 — Create integration matrix test file (gated)

**File:** `tests/integration/coding_lsp/test_capability_matrix_e2e.py` (new file)

```python
"""Integration capability matrix — requires real server binaries.

All tests in this file are skipped unless the binary is present on PATH.
Run in the Docker harness (which has all binaries installed) per project policy.
Do NOT gate-override on the host machine.
"""
from __future__ import annotations

import shutil
import pytest
from pathlib import Path

from audiagentic.components.coding_lsp.lsp_lifecycle import LspSession, ServerConfig


def _require_binary(*names: str) -> None:
    for name in names:
        if not shutil.which(name):
            pytest.skip(f"Binary not found on PATH: {name}")


# ---------------------------------------------------------------------------
# Python — pyright
# ---------------------------------------------------------------------------

@pytest.fixture()
def pyright_session(tmp_path: Path) -> LspSession:
    _require_binary("pyright-langserver")
    cfg = ServerConfig(
        command=["pyright-langserver", "--stdio"],
        file_extensions=[".py"],
        server_id="pyright",
    )
    session = LspSession(cfg, str(tmp_path))
    session.initialize()
    session.initialized()
    yield session
    session.shutdown()


@pytest.fixture()
def py_file_with_error(tmp_path: Path) -> tuple[Path, str]:
    """A Python file with a known type error and an import."""
    f = tmp_path / "sample.py"
    f.write_text("x: int = 'not an int'\n", encoding="utf-8")
    return f, f.as_uri()


def test_pyright_has_definition_capability(pyright_session: LspSession) -> None:
    assert pyright_session.has_capability("textDocument/definition")


def test_pyright_has_no_workspace_pull(pyright_session: LspSession) -> None:
    assert not pyright_session._supports_workspace_diagnostic()


def test_pyright_file_diagnostics_returns_error(
    pyright_session: LspSession, py_file_with_error: tuple
) -> None:
    path, uri = py_file_with_error
    diags = pyright_session.file_diagnostics(str(path), timeout=15.0)
    assert diags, "Expected at least one diagnostic from pyright for type error"
    severities = {d.get("severity") for d in diags}
    assert 1 in severities, "Expected at least one error-severity diagnostic"


def test_pyright_hover_returns_type_info(
    pyright_session: LspSession, py_file_with_error: tuple
) -> None:
    path, uri = py_file_with_error
    pyright_session.did_open(uri, path.read_text(), "python")
    result = pyright_session.hover(uri, 0, 0)
    assert result is not None


# ---------------------------------------------------------------------------
# Python — ruff
# ---------------------------------------------------------------------------

@pytest.fixture()
def ruff_session(tmp_path: Path) -> LspSession:
    _require_binary("ruff")
    cfg = ServerConfig(
        command=["ruff", "server", "--preview"],
        file_extensions=[".py", ".pyi"],
        server_id="ruff",
    )
    session = LspSession(cfg, str(tmp_path))
    session.initialize()
    session.initialized()
    yield session
    session.shutdown()


@pytest.fixture()
def py_file_with_lint(tmp_path: Path) -> tuple[Path, str]:
    f = tmp_path / "lint.py"
    f.write_text("import os\nimport sys\nx=1\n", encoding="utf-8")
    return f, f.as_uri()


def test_ruff_has_workspace_pull(ruff_session: LspSession) -> None:
    assert ruff_session._supports_workspace_diagnostic()


def test_ruff_has_formatting(ruff_session: LspSession) -> None:
    assert ruff_session.has_capability("textDocument/formatting")


def test_ruff_has_no_definition(ruff_session: LspSession) -> None:
    assert not ruff_session.has_capability("textDocument/definition")


def test_ruff_file_diagnostics_returns_lint(
    ruff_session: LspSession, py_file_with_lint: tuple
) -> None:
    path, uri = py_file_with_lint
    diags = ruff_session.file_diagnostics(str(path), timeout=15.0)
    assert diags, "Expected lint diagnostics from ruff (unused imports, spacing)"


def test_ruff_workspace_diagnostics_returns_data(
    ruff_session: LspSession, py_file_with_lint: tuple
) -> None:
    path, _ = py_file_with_lint
    # Open the file so ruff tracks it
    ruff_session.did_open(path.as_uri(), path.read_text(), "python")
    result = ruff_session._workspace_diagnostics_via_lsp(min_severity=4, limit=0, timeout=20.0)
    assert isinstance(result, dict)
    # At least one file should have diagnostics (the one we opened with lint)
    assert any(result.values()), "Expected workspace pull to return at least one diagnostic"


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------

@pytest.fixture()
def ts_session(tmp_path: Path) -> LspSession:
    _require_binary("typescript-language-server", "tsserver")
    cfg = ServerConfig(
        command=["typescript-language-server", "--stdio"],
        file_extensions=[".ts", ".tsx", ".js"],
        server_id="typescript-language-server",
    )
    session = LspSession(cfg, str(tmp_path))
    session.initialize()
    session.initialized()
    yield session
    session.shutdown()


@pytest.fixture()
def ts_file(tmp_path: Path) -> tuple[Path, str]:
    f = tmp_path / "sample.ts"
    f.write_text("const x: number = 'not a number';\n", encoding="utf-8")
    return f, f.as_uri()


def test_ts_has_definition(ts_session: LspSession) -> None:
    assert ts_session.has_capability("textDocument/definition")


def test_ts_has_type_hierarchy(ts_session: LspSession) -> None:
    assert ts_session.has_capability("textDocument/typeHierarchy")


def test_ts_has_no_workspace_pull(ts_session: LspSession) -> None:
    assert not ts_session._supports_workspace_diagnostic()


def test_ts_file_diagnostics_returns_error(
    ts_session: LspSession, ts_file: tuple
) -> None:
    path, uri = ts_file
    diags = ts_session.file_diagnostics(str(path), timeout=20.0)
    assert diags, "Expected type error diagnostic from ts-server"


# ---------------------------------------------------------------------------
# Rust — rust-analyzer
# ---------------------------------------------------------------------------

@pytest.fixture()
def rust_session(tmp_path: Path) -> LspSession:
    _require_binary("rust-analyzer")
    # rust-analyzer needs a Cargo.toml to work properly
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "test"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    cfg = ServerConfig(
        command=["rust-analyzer"],
        file_extensions=[".rs"],
        server_id="rust-analyzer",
    )
    session = LspSession(cfg, str(tmp_path))
    session.initialize()
    session.initialized()
    yield session
    session.shutdown()


def test_rust_has_definition(rust_session: LspSession) -> None:
    assert rust_session.has_capability("textDocument/definition")


def test_rust_has_inlay_hints(rust_session: LspSession) -> None:
    assert rust_session.has_capability("textDocument/inlayHint")


def test_rust_has_type_hierarchy(rust_session: LspSession) -> None:
    assert rust_session.has_capability("textDocument/typeHierarchy")


def test_rust_has_no_workspace_pull(rust_session: LspSession) -> None:
    assert not rust_session._supports_workspace_diagnostic()
```

---

### Step 4 — Create the `tests/integration/coding_lsp/` package

Create `tests/integration/coding_lsp/__init__.py` (empty file) if it does not exist.
Verify `tests/integration/__init__.py` exists too.

---

### Step 5 — Run and fix any failures

Unit matrix:

```
pytest tests/unit/coding_lsp/test_capability_matrix.py -v
```

Every parametrized `test_has_capability_matrix` case must pass. If any fail, the
fixture sets are wrong (update `capability_sets.py`) or `has_capability` has a
provider-map bug (fix `lsp_lifecycle.py`).

Integration matrix (Docker only):

```
pytest tests/integration/coding_lsp/test_capability_matrix_e2e.py -v
```

All skip unless the binary is present. In the Docker harness, all should run.

---

## Files

| File | Change |
|------|--------|
| `tests/unit/coding_lsp/fixtures/__init__.py` | New empty init |
| `tests/unit/coding_lsp/fixtures/capability_sets.py` | New — recorded capability sets |
| `tests/unit/coding_lsp/test_capability_matrix.py` | New — unit matrix (no binaries) |
| `tests/integration/coding_lsp/__init__.py` | New empty init (if missing) |
| `tests/integration/coding_lsp/test_capability_matrix_e2e.py` | New — integration matrix (gated) |

## Validation

Unit matrix: all parametrized cases pass with no binary on PATH.
A map-key regression (wrong provider key name) fails the parametrized test immediately.
No test hangs — capability-gated methods return empty without calling `send_request`.
Integration matrix: skip cleanly on host; pass in Docker with binaries installed.

## Effort & Risk

Mid. Test authoring only. The integration tier depends on installed binaries —
keep it gated and never gate-override on the host. The unit matrix is fast (~1 s).

## Dependencies

CAP01–CAP05 (tests assert their combined behavior).

## Notes

- The fixture capability sets (`capability_sets.py`) are snapshots from real server
  `initialize` responses. Update them when a server releases new capabilities.
- The parametrized `test_has_capability_matrix` is the primary regression gate —
  if a provider key is ever changed in `has_capability`, it shows up here immediately.
- `test_ruff_workspace_diagnostics_returns_data` is the specific guard against the
  original "pull silently returns nothing" bug that motivated this whole plan.
