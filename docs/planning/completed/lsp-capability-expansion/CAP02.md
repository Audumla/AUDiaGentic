---
id: CAP02
order: 2
plan: plan-lsp-capability-expansion
state: done
validate-first: true
priority: P1
complexity: mid
---

# Python pull diagnostics (document + workspace)

## Description

Add LSP 3.17 pull diagnostics without regressing the existing push path.
Decision: **ruff provides workspace pull** (it advertises `diagnosticProvider.workspaceDiagnostics: true`);
**pyright provides document pull** when it advertises `diagnosticProvider`, else falls back to push.
The pyright `--outputjson` CLI fallback (already built) stays for workspace when no server offers pull.

The client must advertise pull support or servers ignore the requests.
`_client_capabilities()` currently omits `textDocument/diagnostic` and `workspace/diagnostics`.

**Prerequisite:** CAP01 must be complete — this item uses `all_sessions_for_file`.

---

## Exact implementation steps (sequential)

### Step 1 — Advertise pull support in client capabilities

**File:** `src/audiagentic/components/coding_lsp/lsp_lifecycle.py`

In `_client_capabilities()`, add two entries:

**1a.** In the `"textDocument"` dict, after `"inlayHint"`:

```python
"diagnostic": {
    "dynamicRegistration": False,
    "relatedDocumentSupport": False,
},
```

**1b.** In the `"workspace"` dict, after `"configuration"`:

```python
"diagnostics": {
    "refreshSupport": True,
},
```

Full updated `_client_capabilities` workspace section:

```python
"workspace": {
    "symbol": {"dynamicRegistration": False},
    "workspaceFolders": True,
    "configuration": True,
    "diagnostics": {
        "refreshSupport": True,
    },
},
```

These declarations tell servers to include `diagnosticProvider` in their capabilities
and to respond to `textDocument/diagnostic` and `workspace/diagnostic` requests.

**Important:** After this change, re-connect any running ag-lsp subprocess for the
new capabilities to take effect (the session caches capabilities at initialize time).

---

### Step 2 — Add document pull path in `file_diagnostics`

**File:** `src/audiagentic/components/coding_lsp/lsp_lifecycle.py`

Current `file_diagnostics` method (lines 549-569) always uses push (open/sync + wait
for `publishDiagnostics`). Add a document pull branch before the push path.

Replace the method with:

```python
def file_diagnostics(
    self, file_path: str | Path, min_severity: int = 4, timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Get diagnostics for a single file.

    Prefers LSP 3.17 document pull (textDocument/diagnostic) when the server
    advertises diagnosticProvider. Falls back to the publishDiagnostics push
    path for servers that don't support pull (pyright, clangd, rust-analyzer).
    """
    if isinstance(file_path, str) and file_path.startswith("file://"):
        uri = file_path
    else:
        uri = Path(file_path).resolve().as_uri()
    uri = self._canonical_uri(uri)

    if self._supports_document_diagnostic():
        return self._file_diagnostics_via_pull(uri, min_severity, timeout)
    return self._file_diagnostics_via_push(uri, min_severity, timeout)
```

**2a.** Add `_supports_document_diagnostic` method:

```python
def _supports_document_diagnostic(self) -> bool:
    """True if the server advertises LSP 3.17 document pull diagnostics.

    Some servers (ruff) advertise diagnosticProvider as an object with
    interFileDependencies and relatedDocumentSupport. Pyright reports
    diagnosticProvider with workspaceDiagnostics: false but may still
    support document pull. A bool True also means supported.
    """
    provider = self._capabilities.get("diagnosticProvider")
    return provider is not None and provider is not False
```

**2b.** Add `_file_diagnostics_via_pull` method:

```python
def _file_diagnostics_via_pull(
    self, uri: str, min_severity: int, timeout: float,
) -> list[dict[str, Any]]:
    """Pull diagnostics for a single document via textDocument/diagnostic."""
    try:
        result = self.bridge.send_request(
            "textDocument/diagnostic",
            {
                "textDocument": {"uri": uri},
                "identifier": None,
                "previousResultId": None,
            },
            timeout=timeout,
        )
    except Exception as exc:
        raise _lsp_error(
            "EXT-LSP-008",
            "Document pull diagnostics request failed",
            details={"uri": uri, "error": str(exc)},
        )

    if not isinstance(result, dict):
        return []

    kind = result.get("kind")
    if kind == "unchanged":
        # Server says result has not changed — return cached push result if any
        cached = self._diagnostics_cache.get(uri, {})
        diags = cached.get("diagnostics", [])
        return [d for d in diags if isinstance(d, dict) and d.get("severity", 1) <= min_severity]

    # kind == "full" — items contains the full diagnostic list
    items = result.get("items") or []
    return [
        d for d in items
        if isinstance(d, dict) and d.get("severity", 1) <= min_severity
    ]
```

**2c.** Extract the existing push logic into `_file_diagnostics_via_push`:

```python
def _file_diagnostics_via_push(
    self, uri: str, min_severity: int, timeout: float,
) -> list[dict[str, Any]]:
    """Get diagnostics via publishDiagnostics push (open/sync + wait)."""
    self._sync_file_from_disk(uri)
    self._wait_for_publish(uri, timeout=timeout)
    cached = self._diagnostics_cache.get(uri, {})
    diags = cached.get("diagnostics", [])
    return [
        d for d in diags
        if isinstance(d, dict) and d.get("severity", 1) <= min_severity
    ]
```

Note: `_sync_file_from_disk` and `_wait_for_publish` already exist and are unchanged.

---

### Step 3 — Add `typeHierarchyProvider` to `has_capability` map

**File:** `src/audiagentic/components/coding_lsp/lsp_lifecycle.py`

In `has_capability`, the `provider_map` dict (inside the method) needs
`typeHierarchyProvider` which is missing. Add it:

```python
"textDocument/typeHierarchy": "typeHierarchyProvider",
```

This is needed for CAP04's type hierarchy tool. Add it now alongside the pull
capability change so the map is complete for the full surface.

---

### Step 4 — Verify workspace pull branch (already built)

The `_workspace_diagnostics_via_lsp` and `_supports_workspace_diagnostic` methods
were built in the previous session. Verify they are present at lines 422-457 in
`lsp_lifecycle.py`. No changes needed unless the file was reverted.

Confirm the branch ordering in `diagnostics()`:

```python
def diagnostics(self, min_severity=4, limit=0, timeout=30.0):
    if self._supports_workspace_diagnostic():
        return self._workspace_diagnostics_via_lsp(min_severity, limit, timeout)
    return self._workspace_diagnostics_via_cli(min_severity, limit, timeout)
```

This is correct: ruff (which advertises `workspaceDiagnostics: true`) uses LSP pull;
pyright (which does not) uses CLI batch scan.

---

### Step 5 — Add tests for pull path

**File:** `tests/unit/coding_lsp/test_lsp_lifecycle.py`

Add the following tests:

```python
def test_supports_document_diagnostic_when_provider_present() -> None:
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {"diagnosticProvider": {"interFileDependencies": False}}
    assert session._supports_document_diagnostic() is True


def test_supports_document_diagnostic_false_when_absent() -> None:
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {}
    assert session._supports_document_diagnostic() is False


def test_file_diagnostics_uses_pull_when_provider_advertised() -> None:
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {"diagnosticProvider": {"workspaceDiagnostics": False}}
    session.bridge = MagicMock()
    session.bridge.send_request = MagicMock(return_value={
        "kind": "full",
        "items": [{"severity": 1, "message": "err", "range": {}}],
    })
    # Patch _sync_file_from_disk to avoid disk I/O
    with patch.object(session, "_sync_file_from_disk"):
        result = session.file_diagnostics("file:///h:/foo.py")
    session.bridge.send_request.assert_called_once()
    method_used = session.bridge.send_request.call_args[0][0]
    assert method_used == "textDocument/diagnostic"
    assert len(result) == 1


def test_file_diagnostics_uses_push_when_no_provider() -> None:
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {}  # no diagnosticProvider
    session._diagnostics_cache["file:///h:/foo.py"] = {
        "diagnostics": [{"severity": 2, "message": "warn", "range": {}}],
        "version": 1,
    }
    session._last_change_version["file:///h:/foo.py"] = 1
    with patch.object(session, "_sync_file_from_disk"):
        result = session.file_diagnostics("file:///h:/foo.py")
    assert result[0]["message"] == "warn"


def test_file_diagnostics_pull_unchanged_returns_cached() -> None:
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {"diagnosticProvider": True}
    session._diagnostics_cache["file:///h:/foo.py"] = {
        "diagnostics": [{"severity": 1, "message": "cached", "range": {}}],
        "version": 1,
    }
    session.bridge = MagicMock()
    session.bridge.send_request = MagicMock(return_value={"kind": "unchanged"})
    with patch.object(session, "_sync_file_from_disk"):
        result = session.file_diagnostics("file:///h:/foo.py")
    assert result[0]["message"] == "cached"


def test_client_capabilities_advertises_pull_diagnostic() -> None:
    caps = LspSession._client_capabilities()
    assert "diagnostic" in caps["textDocument"]
    assert caps["textDocument"]["diagnostic"]["dynamicRegistration"] is False
    assert "diagnostics" in caps["workspace"]
    assert caps["workspace"]["diagnostics"]["refreshSupport"] is True
```

`patch.object` requires `from unittest.mock import patch` — add to the test file's
imports if not already present.

---

## Files

| File | Change |
|------|--------|
| `src/audiagentic/components/coding_lsp/lsp_lifecycle.py` | Add `textDocument/diagnostic` + `workspace/diagnostics` to client caps; add `_supports_document_diagnostic`, `_file_diagnostics_via_pull`, `_file_diagnostics_via_push`; refactor `file_diagnostics`; add `typeHierarchyProvider` to `has_capability` map |
| `tests/unit/coding_lsp/test_lsp_lifecycle.py` | 5 new pull-path tests |

## Validation

```
pytest tests/unit/coding_lsp/test_lsp_lifecycle.py -x -q
```

- Pull path: server with `diagnosticProvider` → `textDocument/diagnostic` sent.
- Push path: server without `diagnosticProvider` → push wait used.
- `unchanged` response → cached push result returned.
- Client caps advertise `textDocument.diagnostic` and `workspace.diagnostics`.
- Path taken asserted (not just output shape) — prevents silent empty regression.

## Effort & Risk

Mid. The push fallback is the existing path, so only the pull branch is new code.
Risk: `"kind": "unchanged"` response is easy to handle wrong (must return cached
push result, not empty list). The `test_file_diagnostics_pull_unchanged_returns_cached`
test guards this.

## Dependencies

CAP01 (session selection). CAP03 (ruff supplies workspace pull in practice).

## Notes

Keep push as universal fallback — most servers (ts, rust-analyzer, clangd) are
push-only. Pull is an optimization where advertised, never an assumption.
`_supports_document_diagnostic` is intentionally separate from
`_supports_workspace_diagnostic` — document pull and workspace pull are
independent advertised capabilities.
