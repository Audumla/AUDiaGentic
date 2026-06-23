---
id: CAP05
order: 5
plan: plan-lsp-capability-expansion
state: not_done
validate-first: true
priority: P2
complexity: complex
---

# Config-gated mutation tools

## Description

Add mutating apply tools that write changes to disk, but expose them **only when
`mutation-enabled: true`** is set in the component config. Default is `false`.
`lsp_capabilities` must mirror the enabled state — a disabled mutation method is
neither advertised nor callable, as if it does not exist.

Mutation tools:
- `lsp_apply_code_action(file, action_index)` — execute a code action and apply the `WorkspaceEdit`
- `lsp_apply_format(file)` — format and write to disk
- `lsp_apply_organize_imports(file)` — organize imports and write to disk
- `lsp_apply_rename(file, position, new_name)` — apply rename edit to disk

**Prerequisites:** CAP01 (session routing), CAP04 (shares codeAction/formatting plumbing).

---

## Exact implementation steps (sequential)

### Step 1 — Add `mutation-enabled` to the component options schema

**File:** `src/audiagentic/config/components/coding-lsp/ag-lsp.yaml`

Open the file and add a `mutation-enabled` field to the options schema. The exact
location depends on whether `ag-lsp.yaml` already has an `options-schema` section.
If it does, add the field; if not, add the section:

```yaml
options-schema:
  mutation-enabled:
    type: boolean
    default: false
    description: >
      Allow mutation tools (lsp_apply_*) that write changes to disk.
      When false (default), apply tools are absent from the MCP surface
      and lsp_capabilities does not report mutation methods.
```

If the options schema lives in a different file (check
`src/audiagentic/config/components/coding-lsp/`), find the implementation descriptor
that defines the top-level component options and add it there.

---

### Step 2 — Add `mutation_enabled()` resolver in `lsp_api.py`

**File:** `src/audiagentic/components/coding_lsp/lsp_api.py`

Add this function near the top (after the imports, before `shutdown_all_sessions`):

```python
def mutation_enabled(project_root: Path | None = None) -> bool:
    """Return True if mutation tools are enabled for the project root.

    Reads the component option `mutation-enabled` from project feature state.
    Defaults to False when the option is absent or the root is unknown.
    """
    if project_root is None:
        return False
    try:
        from audiagentic.foundation.components.ids import COMPONENT_CODING_LSP
        from audiagentic.foundation.features.state import get_component_state
        state = get_component_state(project_root, COMPONENT_CODING_LSP)
        return bool(state.get("options", {}).get("mutation-enabled", False))
    except Exception:
        return False
```

---

### Step 3 — Add `_apply_workspace_edit` helper to `LspSession`

**File:** `src/audiagentic/components/coding_lsp/lsp_lifecycle.py`

This helper converts an LSP `WorkspaceEdit` into disk writes atomically.
Add after the existing `range_formatting` method:

```python
def apply_workspace_edit(
    self, edit: dict[str, Any],
) -> dict[str, Any]:
    """Apply an LSP WorkspaceEdit to disk atomically.

    Writes each file's accumulated text edits by re-reading the file,
    applying edits in reverse document order, then writing via temp-file +
    replace to avoid partial writes. Returns a summary of changed files.

    Raises EXT-LSP-006 on file read/write failure.
    """
    import tempfile
    import shutil as _shutil

    changed_files: list[str] = []
    errors: list[str] = []

    # Collect edits keyed by URI
    edits_by_uri: dict[str, list[dict[str, Any]]] = {}

    # Handle both 'changes' (dict[uri, TextEdit[]]) and 'documentChanges'
    changes = edit.get("changes", {})
    for uri, text_edits in changes.items():
        edits_by_uri.setdefault(self._canonical_uri(uri), []).extend(text_edits)

    for doc_change in (edit.get("documentChanges") or []):
        if not isinstance(doc_change, dict):
            continue
        if "edits" in doc_change:
            # TextDocumentEdit
            uri = self._canonical_uri(doc_change.get("textDocument", {}).get("uri", ""))
            edits_by_uri.setdefault(uri, []).extend(doc_change["edits"])

    for uri, text_edits in edits_by_uri.items():
        path = self._uri_to_path(uri)
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{path}: read failed: {exc}")
            continue

        # Apply edits in reverse order so line numbers stay valid
        lines = original.splitlines(keepends=True)
        sorted_edits = sorted(
            text_edits,
            key=lambda e: (
                e.get("range", {}).get("start", {}).get("line", 0),
                e.get("range", {}).get("start", {}).get("character", 0),
            ),
            reverse=True,
        )
        for text_edit in sorted_edits:
            rng = text_edit.get("range", {})
            start = rng.get("start", {})
            end = rng.get("end", {})
            sl, sc = start.get("line", 0), start.get("character", 0)
            el, ec = end.get("line", 0), end.get("character", 0)
            new_text = text_edit.get("newText", "")

            # Rebuild the affected region character-by-character
            if sl == el:
                if sl < len(lines):
                    line = lines[sl]
                    lines[sl] = line[:sc] + new_text + line[ec:]
            else:
                # Multi-line replacement
                first_line = lines[sl][:sc] if sl < len(lines) else ""
                last_line = lines[el][ec:] if el < len(lines) else ""
                replacement = (first_line + new_text + last_line).splitlines(keepends=True)
                if not replacement and not (first_line + new_text + last_line).endswith("\n"):
                    replacement = [first_line + new_text + last_line]
                lines[sl:el + 1] = replacement

        result_text = "".join(lines)

        # Atomic write via temp file
        try:
            tmp = path.with_suffix(path.suffix + ".lsp_tmp")
            tmp.write_text(result_text, encoding="utf-8")
            _shutil.move(str(tmp), str(path))
            changed_files.append(str(path))
        except OSError as exc:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            errors.append(f"{path}: write failed: {exc}")

    return {"changed_files": changed_files, "errors": errors, "edit_count": len(edits_by_uri)}
```

---

### Step 4 — Add session-level apply methods

**File:** `src/audiagentic/components/coding_lsp/lsp_lifecycle.py`

Add after `apply_workspace_edit`:

```python
def apply_format(
    self, uri: str, options: dict[str, Any] | None = None, timeout: float = 15.0,
) -> dict[str, Any]:
    """Format and write a file to disk.

    Requires mutation to be enabled at the API layer — call site must gate.
    """
    if not self.has_capability("textDocument/formatting"):
        raise _lsp_error(
            "EXT-LSP-004",
            "Server does not support textDocument/formatting",
            details={"uri": uri},
        )
    edits = self.formatting(uri, options, timeout=timeout)
    if not edits:
        return {"changed_files": [], "errors": [], "edit_count": 0, "note": "no changes needed"}
    path = self._uri_to_path(uri)
    edit = {"changes": {uri: edits}}
    return self.apply_workspace_edit(edit)


def apply_organize_imports(
    self, uri: str, timeout: float = 15.0,
) -> dict[str, Any]:
    """Organize imports and write to disk.

    Requires mutation to be enabled at the API layer — call site must gate.
    """
    workspace_edit = self.organize_imports(uri, timeout=timeout)
    if not workspace_edit:
        return {"changed_files": [], "errors": [], "edit_count": 0, "note": "no import changes"}
    return self.apply_workspace_edit(workspace_edit)


def apply_code_action(
    self, uri: str, action: dict[str, Any], timeout: float = 15.0,
) -> dict[str, Any]:
    """Execute a code action (resolve if needed) and apply its WorkspaceEdit.

    `action` is a raw LSP CodeAction object (from `code_actions()`).
    Requires mutation to be enabled at the API layer — call site must gate.
    """
    # Some servers return lazy code actions that need a resolve step
    edit = action.get("edit")
    command = action.get("command")

    if edit is None and command is None:
        # Try to resolve
        try:
            resolved = self.bridge.send_request(
                "codeAction/resolve", action, timeout=timeout,
            )
            if isinstance(resolved, dict):
                edit = resolved.get("edit")
                command = resolved.get("command")
        except Exception:
            pass  # server doesn't support resolve; proceed with what we have

    result: dict[str, Any] = {"changed_files": [], "errors": [], "edit_count": 0}

    if edit:
        result = self.apply_workspace_edit(edit)

    if command and isinstance(command, dict):
        try:
            self.bridge.send_request(
                "workspace/executeCommand",
                {
                    "command": command.get("command", ""),
                    "arguments": command.get("arguments", []),
                },
                timeout=timeout,
            )
        except Exception as exc:
            result["errors"].append(f"executeCommand failed: {exc}")

    return result


def apply_rename(
    self, uri: str, line: int, character: int, new_name: str, timeout: float = 30.0,
) -> dict[str, Any]:
    """Apply a rename refactor to disk.

    Requires mutation to be enabled at the API layer — call site must gate.
    """
    workspace_edit = self.rename(uri, line, character, new_name, timeout=timeout)
    if not workspace_edit:
        raise _lsp_error(
            "EXT-LSP-008",
            "Rename returned no edit — symbol may not be renamable at this position",
            details={"uri": uri, "line": line, "character": character, "new_name": new_name},
        )
    return self.apply_workspace_edit(workspace_edit)
```

---

### Step 5 — Add API functions to `lsp_api.py`

**File:** `src/audiagentic/components/coding_lsp/lsp_api.py`

Add a `_require_mutation` guard helper:

```python
def _require_mutation(project_root: Path) -> None:
    """Raise EXT-LSP-005 if mutation is not enabled for this project root."""
    from audiagentic.foundation.contracts.errors import make_error
    if not mutation_enabled(project_root):
        raise make_error(
            prefix="EXT",
            component="LSP",
            number=5,
            kind="coding-lsp",
            message=(
                "Mutation tools are disabled. Set mutation-enabled: true in the "
                "coding-lsp component config to enable lsp_apply_* tools."
            ),
            details={"project_root": str(project_root)},
        )
```

Add the four API functions after the existing `rename_preview`:

```python
def apply_format(file: str) -> dict[str, Any]:
    """Format and write file to disk. Requires mutation-enabled: true."""
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    _require_mutation(project_root)
    session, uri = _open_file_session(file, "textDocument/formatting")
    if isinstance(session, dict):
        return session
    return session.apply_format(uri)


def apply_organize_imports(file: str) -> dict[str, Any]:
    """Organize imports and write file to disk. Requires mutation-enabled: true."""
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    _require_mutation(project_root)
    session, uri = _open_file_session(file, "textDocument/codeAction")
    if isinstance(session, dict):
        return session
    return session.apply_organize_imports(uri)


def apply_code_action(file: str, action_index: int) -> dict[str, Any]:
    """Execute a code action by index and apply its edit to disk.

    Get the action list first via lsp_code_actions(file), then pass the
    0-based index of the action to apply.
    Requires mutation-enabled: true.
    """
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    _require_mutation(project_root)
    session, uri = _open_file_session(file, "textDocument/codeAction")
    if isinstance(session, dict):
        return session
    actions = session.code_actions(uri, None)
    if action_index < 0 or action_index >= len(actions):
        from audiagentic.foundation.contracts.errors import make_error
        raise make_error(
            prefix="EXT", component="LSP", number=9, kind="coding-lsp",
            message=f"action_index {action_index} out of range (0–{len(actions)-1})",
            details={"file": file, "action_count": len(actions)},
        )
    return session.apply_code_action(uri, actions[action_index])


def apply_rename(file: str, position: str, new_name: str) -> dict[str, Any]:
    """Apply a rename refactor to disk. Requires mutation-enabled: true."""
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    _require_mutation(project_root)
    session, uri = _open_file_session(file, "textDocument/rename")
    if isinstance(session, dict):
        return session
    line, character = parse_position(position)
    return session.apply_rename(uri, line, character, new_name)
```

---

### Step 6 — Register MCP tools conditionally in `lsp_mcp.py`

**File:** `src/audiagentic/components/coding_lsp/lsp_mcp.py`

Mutation tools must not appear in the MCP surface when disabled. The MCP server is a
long-lived process, so tool registration must happen at startup based on the detected
config. Add the following block **after** the existing tool registrations, at module
level (not inside a function):

```python
def _register_mutation_tools() -> None:
    """Register mutation tools if enabled for the current project root.

    Called once at startup. Tools are registered only when mutation-enabled: true
    in the component config. If disabled, the tools are absent from the MCP surface.
    """
    import os
    from pathlib import Path as _Path
    from audiagentic.components.coding_lsp.lsp_api import mutation_enabled, resolve_project_root

    # Detect project root from CWD (ag-lsp is spawned from the project dir)
    try:
        root = resolve_project_root(_Path(os.getcwd()))
    except Exception:
        return  # Can't determine root — skip mutation tools

    if not mutation_enabled(root):
        return

    @mcp.tool()
    @log_tool_call
    def lsp_apply_format(file: str) -> dict[str, Any]:
        """Format a file and write the result to disk.

        MUTATING: writes the formatted content to the file.
        Requires mutation-enabled: true in the coding-lsp component config.
        Use lsp_format_preview(file) to review changes before applying.
        """
        return lsp_api.apply_format(file)

    @mcp.tool()
    @log_tool_call
    def lsp_apply_organize_imports(file: str) -> dict[str, Any]:
        """Organize imports in a file and write to disk.

        MUTATING: rewrites the file's import section.
        Use lsp_organize_imports_preview(file) to review before applying.
        """
        return lsp_api.apply_organize_imports(file)

    @mcp.tool()
    @log_tool_call
    def lsp_apply_code_action(file: str, action_index: int) -> dict[str, Any]:
        """Apply a code action (quick fix, refactor) to disk.

        MUTATING: applies the WorkspaceEdit from the action to one or more files.
        Get the action list first via lsp_code_actions(file).
        action_index: 0-based index into the list returned by lsp_code_actions.
        """
        return lsp_api.apply_code_action(file, action_index)

    @mcp.tool()
    @log_tool_call
    def lsp_apply_rename(file: str, position: str, new_name: str) -> dict[str, Any]:
        """Apply a rename refactor across the workspace and write all changes to disk.

        MUTATING: modifies all files that reference the renamed symbol.
        Use lsp_rename_preview(file, position, new_name) to review before applying.
        position: "line:column" string, 1-based.
        """
        return lsp_api.apply_rename(file, position, new_name)


_register_mutation_tools()
```

---

### Step 7 — Update `lsp_capabilities` to mirror mutation-enabled state

**File:** `src/audiagentic/components/coding_lsp/lsp_api.py`

In `server_capabilities`, after the existing supported-methods union is built,
filter out mutation methods when `mutation_enabled` is False:

```python
_MUTATION_METHODS = {
    "textDocument/formatting",
    "textDocument/rangeFormatting",
    "textDocument/rename",
    "textDocument/codeAction",
}

def server_capabilities(file: str) -> dict[str, Any]:
    # ... existing code from CAP01 ...
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    is_mutation = mutation_enabled(project_root)

    # ... build servers_out and all_supported as in CAP01 ...

    # Remove mutation methods from supported list when disabled
    if not is_mutation:
        all_supported = {
            s for s in all_supported
            if s not in {"formatting", "rangeFormatting", "rename", "codeAction"}
        }

    return {
        "language": language,
        "servers": servers_out,
        "supported": sorted(all_supported),
        "mutation_enabled": is_mutation,
    }
```

The label names to filter (`"formatting"`, `"rangeFormatting"`, `"rename"`,
`"codeAction"`) match those in `method_labels` dict inside `server_capabilities`.
Add `"mutation_enabled"` to the response so callers know whether apply tools exist.

---

### Step 8 — Add tests

**File:** `tests/unit/coding_lsp/test_lsp_lifecycle.py`

```python
def test_apply_workspace_edit_writes_file(tmp_path) -> None:
    """apply_workspace_edit writes the formatted text to disk."""
    target = tmp_path / "foo.py"
    target.write_text("x=1\n", encoding="utf-8")
    uri = target.as_uri()
    session = LspSession(_make_config(), str(tmp_path))
    edit = {
        "changes": {
            uri: [{"range": {"start": {"line": 0, "character": 0},
                             "end": {"line": 0, "character": 3}},
                   "newText": "x = 1"}]
        }
    }
    result = session.apply_workspace_edit(edit)
    assert result["changed_files"]
    assert target.read_text(encoding="utf-8") == "x = 1\n"


def test_apply_workspace_edit_atomic_on_error(tmp_path) -> None:
    """Temp file is cleaned up if write fails; original file preserved."""
    import unittest.mock as _mock
    target = tmp_path / "foo.py"
    target.write_text("original\n", encoding="utf-8")
    uri = target.as_uri()
    session = LspSession(_make_config(), str(tmp_path))
    edit = {"changes": {uri: [{"range": {"start": {"line": 0, "character": 0},
                                          "end": {"line": 0, "character": 8}},
                                "newText": "replaced"}]}}
    import shutil
    with _mock.patch("shutil.move", side_effect=OSError("disk full")):
        result = session.apply_workspace_edit(edit)
    assert result["errors"]
    assert target.read_text(encoding="utf-8") == "original\n"
```

**File:** `tests/unit/coding_lsp/test_lsp_api.py`

```python
def test_require_mutation_raises_when_disabled() -> None:
    from pathlib import Path
    from unittest.mock import patch
    from audiagentic.components.coding_lsp.lsp_api import _require_mutation
    with patch("audiagentic.components.coding_lsp.lsp_api.mutation_enabled", return_value=False):
        try:
            _require_mutation(Path("/tmp"))
            assert False, "Expected error"
        except Exception as exc:
            assert "mutation" in str(exc).lower()


def test_server_capabilities_omits_mutation_when_disabled() -> None:
    from unittest.mock import MagicMock, patch
    from audiagentic.components.coding_lsp.lsp_lifecycle import ServerConfig
    from audiagentic.components.coding_lsp import lsp_api

    cfg = ServerConfig(
        command=["pyright-langserver", "--stdio"], file_extensions=[".py"], server_id="pyright"
    )
    mock_session = MagicMock()
    mock_session.has_capability.return_value = True
    mock_session.capabilities.return_value = {
        "definitionProvider": True,
        "documentFormattingProvider": True,
        "renameProvider": True,
    }

    with patch("audiagentic.components.coding_lsp.lsp_api._resolve_language_servers_for_file",
               return_value=[("python", cfg)]):
        with patch("audiagentic.components.coding_lsp.lsp_api._session_manager") as mock_mgr:
            with patch("audiagentic.components.coding_lsp.lsp_api.mutation_enabled", return_value=False):
                mock_mgr.get_or_create.return_value = mock_session
                result = lsp_api.server_capabilities("src/foo.py")

    assert "formatting" not in result["supported"]
    assert "rename" not in result["supported"]
    assert result["mutation_enabled"] is False
```

---

## Files

| File | Change |
|------|--------|
| `src/audiagentic/config/components/coding-lsp/ag-lsp.yaml` | Add `mutation-enabled: false` to options-schema |
| `src/audiagentic/components/coding_lsp/lsp_lifecycle.py` | Add `apply_workspace_edit`, `apply_format`, `apply_organize_imports`, `apply_code_action`, `apply_rename` methods |
| `src/audiagentic/components/coding_lsp/lsp_api.py` | Add `mutation_enabled()`, `_require_mutation()`, 4 apply functions; filter caps when disabled |
| `src/audiagentic/components/coding_lsp/lsp_mcp.py` | Add `_register_mutation_tools()` called at module init |
| `tests/unit/coding_lsp/test_lsp_lifecycle.py` | 2 new apply tests |
| `tests/unit/coding_lsp/test_lsp_api.py` | 2 new mutation-gate tests |

## Validation

```
pytest tests/unit/coding_lsp/ -x -q
```

With `mutation-enabled: false` (default):
- `lsp_apply_*` tools not registered in MCP server
- `lsp_capabilities` omits `formatting`, `rangeFormatting`, `rename`, `codeAction`
- `_require_mutation` raises EXT-LSP-005

With `mutation-enabled: true`:
- `lsp_apply_format` writes formatted content and returns `changed_files`
- `lsp_apply_workspace_edit` writes atomically (temp + replace)
- Error on write failure does not corrupt original file
- `lsp_capabilities` includes mutation methods where the server supports them

## Effort & Risk

Highest risk in this plan — writes user files. Mitigations:
1. Default off: must explicitly set `mutation-enabled: true`
2. Atomic writes: temp file + `shutil.move`, original untouched on failure
3. Re-read before apply: edits applied to current disk state, not stale buffer
4. `_require_mutation` gate at API level: even if MCP tools were somehow invoked,
   the API refuses the call if the project root is disabled

## Dependencies

CAP01, CAP04.

## Notes

- `lsp_apply_code_action` requires the caller to first run `lsp_code_actions(file)`
  and pass the 0-based index. This two-step design lets agents inspect before applying.
- `apply_workspace_edit` handles both `changes` (simple dict) and `documentChanges`
  (array with versioning). Version checks are skipped — the apply is best-effort on
  current disk state.
- Edits within a single file are applied in reverse line order so earlier line numbers
  remain valid as each edit is applied.
- `workspace/executeCommand` is called for code actions that have a command but no
  edit. This is fire-and-forget from our side (no apply needed if the server modifies
  files via its own mechanism).
