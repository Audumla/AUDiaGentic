---
id: CAP03
order: 3
plan: lsp-capability-expansion
state: done
validate-first: true
priority: P1
work: M
---

# Ruff as a second Python server

## Description

Register ruff's built-in language server (`ruff server`) as a second Python server
alongside pyright. ruff supplies lint diagnostics (`E/F/I/UP/...`), formatting, and
organize-imports, and advertises workspace pull diagnostics. pyright keeps types,
navigation, and document pull.

Diagnostics merge via CAP01's dedup logic. Routing: ruff is preferred for formatting
and lint code actions; pyright for navigation (definition, hover, references).

**Prerequisites:** CAP01 (multi-server infrastructure), CAP02 (pull paths).

---

## Exact implementation steps (sequential)

### Step 1 — Create ruff language feature YAML

**File:** `src/audiagentic/config/components/coding-lsp/python-ruff.yaml` (new file)

```yaml
type: feature
contract-version: v1
parent: coding-lsp
kind: language
id: python-ruff
display-name: Python (ruff)
language-id: python
server:
  command: [ruff, server, --preview]
  file-extensions: [.py, .pyi, .ipynb]
  workspace-config-files: [ruff.toml, pyproject.toml, .ruff.toml]
detection-markers: [pyproject.toml, ruff.toml, .ruff.toml]
dependencies:
  ruff:
    display-name: Ruff (Python linter/formatter LSP)
    probe: binary:ruff
    toolchain: uv
    package: ruff
    uninstall-package: ruff
    requires:
      min-version: "0.4.0"
options-schema:
  server-settings:
    type: object
    default: {}
```

Notes on this YAML:
- `id: python-ruff` — distinct feature id so it's a separate registry entry
- `language-id: python` — same LSP language ID as pyright, so `did_open` uses `"python"`
- `--preview` flag enables all ruff server features; remove if too noisy
- `min-version: "0.4.0"` — first release with stable `ruff server` subcommand

---

### Step 2 — Register the implementation binding

**File:** `src/audiagentic/config/components/coding-lsp/ag-lsp.python-ruff.yaml` (new file)

Look at `src/audiagentic/config/components/coding-lsp/ag-lsp.python.yaml` for the
binding format. Create an analogous file for `python-ruff`:

```yaml
type: binding
contract-version: v1
parent: coding-lsp
implementation: ag-lsp
feature-kind: language
feature: python-ruff
default-enabled: false
```

Set `default-enabled: false` — ruff is opt-in until the project confirms ruff is
installed. The user (or auto-detect logic in CAP07) enables it per project.

---

### Step 3 — Verify registry loads the new feature

Run the test suite after adding the YAML:

```
pytest tests/unit/coding_lsp/test_language_registry.py -x -q
```

If tests fail due to the new `python-ruff` id, check
`src/audiagentic/components/coding_lsp/language_registry.py:_is_language_feature`
(line 66-71). The function validates `type`, `kind`, and `parent` — all correct in
the new YAML. If the registry test asserts a fixed language list, update the assertion
to include `python-ruff`.

---

### Step 4 — Enable ruff per-project in the test fixture

When testing, the session manager needs both `python` and `python-ruff` enabled.
The resolver (after CAP01) collects all enabled language features, so enabling
`python-ruff` feature state in a project will cause both servers to appear in
`resolve_active_runtime_servers`.

For unit tests, mock the resolver to return both:

```python
{
    "python": [
        ServerConfig(command=["pyright-langserver", "--stdio"], file_extensions=[".py"], server_id="pyright"),
        ServerConfig(command=["ruff", "server", "--preview"], file_extensions=[".py", ".pyi"], server_id="ruff"),
    ]
}
```

---

### Step 5 — Add routing preference for ruff capabilities

**File:** `src/audiagentic/components/coding_lsp/lsp_api.py`

The `_open_file_session(file, method)` added in CAP01 already routes to the first
capable server via `pick_capable`. Ruff's `documentFormattingProvider` will be
present in its capabilities; pyright's will not. So `format_preview` automatically
routes to ruff.

For diagnostics, the existing merge in `SessionManager.diagnostics` and the updated
`file_diagnostics` in `lsp_api.py` (CAP01 step 4g) already merge all sessions.
No additional routing code needed for diagnostics.

For `organize_imports_preview`, ruff advertises `codeActionProvider` with
`source.organizeImports` kind. Since `_open_file_session` passes
`"textDocument/codeAction"` as the method and ruff supports it, ruff will be
preferred when both servers support it (it appears first in the list). Verify ruff
is ordered before pyright by checking `runtime_resolver.py` iteration order.

If ordering needs to be explicit, add a `priority` field to the YAML and sort by it
in `resolve_active_runtime_servers`. For now, rely on registration order (pyright
first, ruff second) — pyright is preferred for navigation, ruff for formatting
because only ruff advertises formatting.

---

### Step 6 — Confirm ruff workspace pull wires into CAP02's branch

Ruff's capabilities object includes:

```json
{
  "diagnosticProvider": {
    "identifier": "ruff",
    "interFileDependencies": false,
    "workspaceDiagnostics": true
  }
}
```

The `_supports_workspace_diagnostic()` method (CAP01, already present) checks
`diagnosticProvider.workspaceDiagnostics` — this will return `True` for ruff.
The `_supports_document_diagnostic()` method (CAP02) checks `diagnosticProvider` is
not None/False — also `True` for ruff.

So for ruff sessions:
- `file_diagnostics` → uses `textDocument/diagnostic` (document pull) via CAP02
- `diagnostics` (workspace) → uses `workspace/diagnostic` (workspace pull) via existing code

No code changes needed beyond CAP01 + CAP02.

---

### Step 7 — Add `_BATCH_DIAGNOSTIC_CLIS` entry (not needed for ruff)

Ruff uses LSP pull for workspace diagnostics, not a CLI batch scan. No entry needed
in `_BATCH_DIAGNOSTIC_CLIS`. If ruff is the session and workspace pull is supported,
the LSP path is taken. The CLI fallback is only for pyright/basedpyright.

---

### Step 8 — Update `_path_to_language_id` to handle `.ipynb`

**File:** `src/audiagentic/components/coding_lsp/lsp_lifecycle.py`

Ruff supports `.ipynb` files. The `_path_to_language_id` static method (line 683)
maps extensions to LSP language IDs. Add:

```python
"ipynb": "jupyter",
```

Ruff expects `languageId: "jupyter"` for notebook files; the ruff YAML already lists
`.ipynb` in `file-extensions`.

---

### Step 9 — Update install recipe (preview of CAP07)

The YAML `dependencies.ruff` block (step 1) is the install recipe. Verify it round-
trips through `language_registry.dependency_cfgs(["python-ruff"])` correctly. Run:

```
pytest tests/unit/coding_lsp/test_language_registry.py -x -q -k ruff
```

If no test covers `dependency_cfgs` for `python-ruff`, add one:

```python
def test_python_ruff_dependency_cfg_present() -> None:
    from audiagentic.components.coding_lsp import language_registry
    cfgs = language_registry.dependency_cfgs(["python-ruff"])
    assert "ruff" in cfgs
    assert cfgs["ruff"]["probe"] == "binary:ruff"
```

---

### Step 10 — Add integration-style unit tests for two-server Python

**File:** `tests/unit/coding_lsp/test_lsp_api.py`

```python
def test_file_diagnostics_merges_pyright_and_ruff() -> None:
    """Both servers' diagnostics appear in merged result, deduped."""
    from unittest.mock import MagicMock, patch
    from audiagentic.components.coding_lsp.lsp_lifecycle import ServerConfig

    pyright_diag = {"severity": 1, "message": "type error", "range": {}, "source": "pyright", "code": "reportX"}
    ruff_diag = {"severity": 2, "message": "lint error", "range": {}, "source": "ruff", "code": "E501"}

    pyright_cfg = ServerConfig(command=["pyright-langserver", "--stdio"], file_extensions=[".py"], server_id="pyright")
    ruff_cfg = ServerConfig(command=["ruff", "server"], file_extensions=[".py"], server_id="ruff")

    mock_pyright = MagicMock()
    mock_pyright.has_capability.return_value = True
    mock_pyright.file_diagnostics.return_value = [pyright_diag]

    mock_ruff = MagicMock()
    mock_ruff.has_capability.return_value = True
    mock_ruff.file_diagnostics.return_value = [ruff_diag]

    with patch("audiagentic.components.coding_lsp.lsp_api._resolve_language_servers_for_file",
               return_value=[("python", pyright_cfg), ("python", ruff_cfg)]):
        with patch("audiagentic.components.coding_lsp.lsp_api._session_manager") as mock_mgr:
            mock_mgr.get_or_create.side_effect = lambda root, lang, cfg: (
                mock_pyright if cfg.server_id == "pyright" else mock_ruff
            )
            from audiagentic.components.coding_lsp import lsp_api
            result = lsp_api.file_diagnostics("src/foo.py")

    assert len(result) == 2
    sources = {d["source"] for d in result}
    assert sources == {"pyright", "ruff"}


def test_format_preview_routes_to_ruff_not_pyright() -> None:
    """format_preview picks the server that advertises documentFormattingProvider."""
    from unittest.mock import MagicMock, patch
    from audiagentic.components.coding_lsp.lsp_lifecycle import ServerConfig

    pyright_cfg = ServerConfig(command=["pyright-langserver", "--stdio"], file_extensions=[".py"], server_id="pyright")
    ruff_cfg = ServerConfig(command=["ruff", "server"], file_extensions=[".py"], server_id="ruff")

    mock_pyright = MagicMock()
    mock_pyright.has_capability.side_effect = lambda m: m != "textDocument/formatting"
    mock_pyright.formatting.return_value = []

    mock_ruff = MagicMock()
    mock_ruff.has_capability.side_effect = lambda m: True
    mock_ruff.formatting.return_value = [{"range": {}, "newText": "formatted"}]
    mock_ruff.sync_document = MagicMock()

    with patch("audiagentic.components.coding_lsp.lsp_api._resolve_language_servers_for_file",
               return_value=[("python", pyright_cfg), ("python", ruff_cfg)]):
        with patch("audiagentic.components.coding_lsp.lsp_api._session_manager") as mock_mgr:
            with patch("pathlib.Path.read_text", return_value="x=1"):
                mock_mgr.get_or_create.side_effect = lambda root, lang, cfg: (
                    mock_pyright if cfg.server_id == "pyright" else mock_ruff
                )
                from audiagentic.components.coding_lsp import lsp_api
                result = lsp_api.format_preview("src/foo.py")

    assert result is not None
    mock_ruff.formatting.assert_called_once()
    mock_pyright.formatting.assert_not_called()
```

---

## Files

| File | Change |
|------|--------|
| `src/audiagentic/config/components/coding-lsp/python-ruff.yaml` | New — ruff language feature YAML |
| `src/audiagentic/config/components/coding-lsp/ag-lsp.python-ruff.yaml` | New — implementation binding (default-enabled: false) |
| `src/audiagentic/components/coding_lsp/lsp_lifecycle.py` | Add `"ipynb": "jupyter"` to `_path_to_language_id` |
| `tests/unit/coding_lsp/test_language_registry.py` | Add `python-ruff` dependency cfg test |
| `tests/unit/coding_lsp/test_lsp_api.py` | 2 new routing tests |

## Validation

```
pytest tests/unit/coding_lsp/ -x -q
```

- Registry loads `python-ruff` without error
- `dependency_cfgs(["python-ruff"])` returns ruff probe/install block
- `file_diagnostics` for a Python file returns merged pyright + ruff diagnostics
- `format_preview` routes to ruff (advertising `documentFormattingProvider`)
- pyright stays for definition/hover (ruff does not advertise `definitionProvider`)
- Workspace diagnostics for `python-ruff` session uses `workspace/diagnostic` pull

## Effort & Risk

Mid. Main risk: ruff YAML id (`python-ruff`) must not collide with the `python` id in
the single-server resolver path from before CAP01. After CAP01, both are in the
`python` language's list. Double-check that `_resolve_language_servers_for_file`
collects both by extension match (`.py` appears in both YAMLs).

## Dependencies

CAP01, CAP02.

## Notes

- `ruff server --preview` is recommended for full feature set; drop `--preview` if
  the project runs a stable-only ruff.
- ruff does NOT provide `definitionProvider`, `hoverProvider`, `referencesProvider`,
  `renameProvider`, or `callHierarchyProvider`. pyright provides those. The
  `pick_capable` routing ensures ruff is never sent those requests.
- To enable ruff for a project: `ag component coding-lsp enable python-ruff` (or
  equivalent feature-state write). The binding YAML's `default-enabled: false` means
  it must be explicitly enabled.
- Minimum ruff version for `ruff server`: 0.4.0 (released 2024-04). Probe the binary
  version before registering in production; the YAML `requires.min-version` field
  documents the constraint even if probing is not yet automatic.
