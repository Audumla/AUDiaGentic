---
id: CAP04
order: 4
plan: plan-lsp-capability-expansion
state: not_done
validate-first: true
priority: P2
complexity: mid
---

# Expand read-only capability tools

## Description

Add four read-only tools the installed servers already advertise but the current
surface does not expose. Each is capability-gated so it no-ops cleanly when a server
lacks support. All four ship together and are independent of each other.

New MCP tools:
- `lsp_inlay_hints(file, start, end)` — inferred types and param names inline
- `lsp_signature_help(file, position)` — param types and overloads at a call site
- `lsp_type_hierarchy(file, position, direction)` — super/subtypes navigation
- `lsp_completion(file, position, limit)` — bounded identifier/member completion

**Prerequisite:** CAP01 (session routing). CAP02 not required but adds pull cap to map.

---

## Exact implementation steps (sequential)

### Step 1 — Add `typeHierarchyProvider` to `has_capability` map (if not done in CAP02)

**File:** `src/audiagentic/components/coding_lsp/lsp_lifecycle.py`

Inside `has_capability`, the `provider_map` dict needs this entry (add after
`"textDocument/callHierarchy": "callHierarchyProvider"`):

```python
"textDocument/typeHierarchy": "typeHierarchyProvider",
```

Verify it is not already present (CAP02 step 3 adds it). If CAP02 ran first, skip.

---

### Step 2 — Add session methods to `LspSession`

**File:** `src/audiagentic/components/coding_lsp/lsp_lifecycle.py`

Add the following four methods to `LspSession`, after the existing `call_hierarchy_outgoing`
method (around line 336). Add them in this order:

#### 2a — `inlay_hints`

```python
def inlay_hints(
    self, uri: str, start_line: int, start_char: int,
    end_line: int, end_char: int, timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Get inlay hints (inferred types, param names) for a range."""
    if not self.has_capability("textDocument/inlayHint"):
        return []
    result = self.bridge.send_request(
        "textDocument/inlayHint",
        {
            "textDocument": {"uri": uri},
            "range": {
                "start": {"line": start_line, "character": start_char},
                "end": {"line": end_line, "character": end_char},
            },
        },
        timeout=timeout,
    )
    return _ensure_list(result)
```

#### 2b — `signature_help`

```python
def signature_help(
    self, uri: str, line: int, character: int, timeout: float = 15.0,
) -> dict[str, Any] | None:
    """Get signature help (param types and overloads) at a call site."""
    if not self.has_capability("textDocument/signatureHelp"):
        return None
    result = self.bridge.send_request(
        "textDocument/signatureHelp",
        {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
            "context": {
                "triggerKind": 1,  # TriggerKind.Invoked
                "isRetrigger": False,
            },
        },
        timeout=timeout,
    )
    return result if isinstance(result, dict) else None
```

#### 2c — `type_hierarchy` (prepare + resolve)

```python
def type_hierarchy_prepare(
    self, uri: str, line: int, character: int, timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Prepare type hierarchy items for the symbol at position."""
    if not self.has_capability("textDocument/typeHierarchy"):
        return []
    result = self.bridge.send_request(
        "textDocument/prepareTypeHierarchy",
        {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        },
        timeout=timeout,
    )
    return _ensure_list(result)


def type_hierarchy_supertypes(
    self, item: dict[str, Any], timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Get supertypes for a type hierarchy item."""
    result = self.bridge.send_request(
        "typeHierarchy/supertypes",
        {"item": item},
        timeout=timeout,
    )
    return _ensure_list(result)


def type_hierarchy_subtypes(
    self, item: dict[str, Any], timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Get subtypes for a type hierarchy item."""
    result = self.bridge.send_request(
        "typeHierarchy/subtypes",
        {"item": item},
        timeout=timeout,
    )
    return _ensure_list(result)
```

#### 2d — `completion`

```python
def completion(
    self, uri: str, line: int, character: int, timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Get completion items at position.

    Returns raw items; callers should apply a limit before returning to agents
    (completion lists can be very large).
    """
    if not self.has_capability("textDocument/completion"):
        return []
    result = self.bridge.send_request(
        "textDocument/completion",
        {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
            "context": {"triggerKind": 1},  # TriggerKind.Invoked
        },
        timeout=timeout,
    )
    if result is None:
        return []
    # Server may return CompletionList or list[CompletionItem]
    if isinstance(result, dict):
        return _ensure_list(result.get("items"))
    return _ensure_list(result)
```

---

### Step 3 — Add normalize helpers to `lsp_api.py`

**File:** `src/audiagentic/components/coding_lsp/lsp_api.py`

Add after `normalize_workspace_edit`:

```python
def normalize_inlay_hint(hint: dict[str, Any]) -> dict[str, Any]:
    """Normalize an LSP InlayHint to consistent schema."""
    pos = hint.get("position", {})
    label = hint.get("label", "")
    if isinstance(label, list):
        # InlayHintLabelPart list — join their values
        label = "".join(part.get("value", "") if isinstance(part, dict) else str(part) for part in label)
    return {
        "line": pos.get("line", 0) + 1,       # 1-based for output
        "character": pos.get("character", 0),
        "label": label,
        "kind": hint.get("kind"),              # 1=Type, 2=Parameter
        "paddingLeft": hint.get("paddingLeft", False),
        "paddingRight": hint.get("paddingRight", False),
    }


def normalize_signature_help(sig: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize an LSP SignatureHelp to consistent schema."""
    if not sig:
        return None
    signatures = sig.get("signatures") or []
    active_sig = sig.get("activeSignature", 0)
    active_param = sig.get("activeParameter")
    normalized_sigs = []
    for s in signatures:
        params = [
            {
                "label": p.get("label", ""),
                "documentation": p.get("documentation", {}).get("value", "")
                if isinstance(p.get("documentation"), dict)
                else str(p.get("documentation", "")),
            }
            for p in (s.get("parameters") or [])
        ]
        normalized_sigs.append({
            "label": s.get("label", ""),
            "documentation": s.get("documentation", {}).get("value", "")
            if isinstance(s.get("documentation"), dict)
            else str(s.get("documentation", "")),
            "parameters": params,
        })
    return {
        "signatures": normalized_sigs,
        "activeSignature": active_sig,
        "activeParameter": active_param,
    }


def normalize_completion_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize an LSP CompletionItem to consistent schema."""
    kind_map = {
        1: "text", 2: "method", 3: "function", 4: "constructor",
        5: "field", 6: "variable", 7: "class", 8: "interface",
        9: "module", 10: "property", 11: "unit", 12: "value",
        13: "enum", 14: "keyword", 15: "snippet", 16: "color",
        17: "file", 18: "reference", 19: "folder", 20: "enum_member",
        21: "constant", 22: "struct", 23: "event", 24: "operator",
        25: "type_parameter",
    }
    doc = item.get("documentation", "")
    if isinstance(doc, dict):
        doc = doc.get("value", "")
    return {
        "label": item.get("label", ""),
        "kind": kind_map.get(item.get("kind", 0), "unknown"),
        "detail": item.get("detail", ""),
        "documentation": doc,
        "sortText": item.get("sortText", item.get("label", "")),
        "insertText": item.get("insertText", item.get("label", "")),
        "deprecated": item.get("deprecated", False),
    }


def normalize_type_hierarchy_item(item: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Normalize an LSP TypeHierarchyItem to consistent schema."""
    return {
        "name": item.get("name", ""),
        "kind": item.get("kind", 0),
        "file": uri_to_repo_relative(item.get("uri", ""), project_root),
        "range": item.get("range", {}),
        "selectionRange": item.get("selectionRange", {}),
        "detail": item.get("detail", ""),
    }
```

---

### Step 4 — Add API functions to `lsp_api.py`

**File:** `src/audiagentic/components/coding_lsp/lsp_api.py`

Add these four functions after the existing `rename_preview` function:

```python
def inlay_hints(
    file: str, start: str, end: str,
) -> list[dict[str, Any]]:
    """Get inlay hints for the range [start, end] in a file.

    start/end: "line:column" strings, 1-based.
    """
    session, uri = _open_file_session(file, "textDocument/inlayHint")
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    sl, sc = parse_position(start)
    el, ec = parse_position(end)
    raw = session.inlay_hints(uri, sl, sc, el, ec)
    return [normalize_inlay_hint(h) for h in raw]


def signature_help(file: str, position: str) -> dict[str, Any] | None:
    """Get signature help at a call-site position.

    position: "line:column" string, 1-based.
    """
    session, uri = _open_file_session(file, "textDocument/signatureHelp")
    if isinstance(session, dict):
        return session
    line, character = parse_position(position)
    raw = session.signature_help(uri, line, character)
    return normalize_signature_help(raw)


def type_hierarchy(
    file: str, position: str, direction: str = "supertypes",
) -> list[dict[str, Any]]:
    """Get type hierarchy (supertypes or subtypes) for the symbol at position.

    direction: "supertypes" (default) or "subtypes".
    position: "line:column" string, 1-based.
    """
    session, uri = _open_file_session(file, "textDocument/typeHierarchy")
    if isinstance(session, dict):
        return [session]
    project_root = resolve_project_root(file)
    line, character = parse_position(position)
    items = session.type_hierarchy_prepare(uri, line, character)
    if not items:
        return []
    results: list[dict[str, Any]] = []
    for item in items:
        if direction == "subtypes":
            children = session.type_hierarchy_subtypes(item)
        else:
            children = session.type_hierarchy_supertypes(item)
        for child in children:
            results.append(normalize_type_hierarchy_item(child, project_root))
    return results


def completion(
    file: str, position: str, limit: int = 20,
) -> list[dict[str, Any]]:
    """Get completion suggestions at position.

    Returns at most `limit` items (default 20), sorted by sortText.
    For discovery only — not a full member listing.
    position: "line:column" string, 1-based.
    """
    session, uri = _open_file_session(file, "textDocument/completion")
    if isinstance(session, dict):
        return [session]
    line, character = parse_position(position)
    raw = session.completion(uri, line, character)
    items = [normalize_completion_item(i) for i in raw if isinstance(i, dict)]
    items.sort(key=lambda x: x.get("sortText", x.get("label", "")))
    return items[:limit] if limit > 0 else items
```

---

### Step 5 — Register MCP tools in `lsp_mcp.py`

**File:** `src/audiagentic/components/coding_lsp/lsp_mcp.py`

Add four new `@mcp.tool()` decorated functions after the existing `lsp_rename_preview`
tool. All four use `@log_tool_call`:

```python
@mcp.tool()
@log_tool_call
def lsp_inlay_hints(file: str, start: str, end: str) -> list[dict[str, Any]]:
    """Get inlay hints (inferred types and parameter names) for a range in a file.

    start/end: "line:column" strings, 1-based (e.g. "1:1" to "50:1" for first 50 lines).
    Returns hints with line, character, label, and kind (1=Type, 2=Parameter).
    Returns empty list when the server does not support inlay hints.
    Check lsp_capabilities(file) first to see if inlayHint is supported.
    """
    return lsp_api.inlay_hints(file, start, end)


@mcp.tool()
@log_tool_call
def lsp_signature_help(file: str, position: str) -> dict[str, Any] | None:
    """Get function signature help (parameter types and overloads) at a call-site position.

    position: "line:column" string, 1-based. Call this at the position INSIDE a function call.
    Returns signatures with label, documentation, and parameters list.
    Returns None when the server does not support signatureHelp or there is no call at position.
    """
    return lsp_api.signature_help(file, position)


@mcp.tool()
@log_tool_call
def lsp_type_hierarchy(
    file: str, position: str, direction: str = "supertypes",
) -> list[dict[str, Any]]:
    """Get type hierarchy (base classes or derived classes) for the symbol at position.

    position: "line:column" string, 1-based.
    direction: "supertypes" (base classes/interfaces, default) or "subtypes" (derived classes).
    Returns normalized items with name, kind, file (repo-relative), and range.
    Returns empty list when the server does not support typeHierarchy.
    """
    return lsp_api.type_hierarchy(file, position, direction)


@mcp.tool()
@log_tool_call
def lsp_completion(
    file: str, position: str, limit: int = 20,
) -> list[dict[str, Any]]:
    """Get code completion suggestions at position.

    position: "line:column" string, 1-based.
    limit: max items to return (default 20). Results are sorted by relevance.
    For discovery and type-checking use, not exhaustive member listing.
    Returns items with label, kind, detail, documentation, and insertText.
    Returns empty list when the server does not support completion.
    """
    return lsp_api.completion(file, position, limit)
```

---

### Step 6 — Add unit tests

**File:** `tests/unit/coding_lsp/test_lsp_lifecycle.py`

```python
def test_inlay_hints_returns_empty_when_no_capability() -> None:
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {}  # no inlayHintProvider
    result = session.inlay_hints("file:///f.py", 0, 0, 10, 0)
    assert result == []


def test_signature_help_returns_none_when_no_capability() -> None:
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {}
    result = session.signature_help("file:///f.py", 5, 10)
    assert result is None


def test_type_hierarchy_prepare_returns_empty_when_no_capability() -> None:
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {}
    result = session.type_hierarchy_prepare("file:///f.py", 5, 10)
    assert result == []


def test_completion_returns_empty_when_no_capability() -> None:
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {}
    result = session.completion("file:///f.py", 5, 10)
    assert result == []


def test_completion_unwraps_completion_list() -> None:
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {"completionProvider": True}
    session.bridge = MagicMock()
    session.bridge.send_request = MagicMock(return_value={
        "isIncomplete": False,
        "items": [{"label": "foo", "kind": 3}],
    })
    result = session.completion("file:///f.py", 5, 10)
    assert result == [{"label": "foo", "kind": 3}]


def test_inlay_hints_sends_range_request() -> None:
    session = LspSession(_make_config(), "/tmp")
    session._capabilities = {"inlayHintProvider": True}
    session.bridge = MagicMock()
    session.bridge.send_request = MagicMock(return_value=[
        {"position": {"line": 2, "character": 5}, "label": ": int", "kind": 1}
    ])
    result = session.inlay_hints("file:///f.py", 0, 0, 10, 0)
    assert len(result) == 1
    assert result[0]["label"] == ": int"
```

**File:** `tests/unit/coding_lsp/test_lsp_api.py`

```python
def test_normalize_inlay_hint_converts_label_parts() -> None:
    from audiagentic.components.coding_lsp.lsp_api import normalize_inlay_hint
    hint = {
        "position": {"line": 2, "character": 5},
        "label": [{"value": ": "}, {"value": "int"}],
        "kind": 1,
    }
    result = normalize_inlay_hint(hint)
    assert result["label"] == ": int"
    assert result["line"] == 3  # 1-based


def test_normalize_completion_item_maps_kind() -> None:
    from audiagentic.components.coding_lsp.lsp_api import normalize_completion_item
    item = {"label": "my_func", "kind": 3, "detail": "() -> None"}
    result = normalize_completion_item(item)
    assert result["kind"] == "function"
    assert result["label"] == "my_func"


def test_completion_limits_results() -> None:
    from unittest.mock import MagicMock, patch
    from audiagentic.components.coding_lsp import lsp_api

    items_50 = [{"label": f"item{i}", "kind": 6} for i in range(50)]
    mock_session = MagicMock()
    mock_session.has_capability.return_value = True
    mock_session.completion.return_value = items_50
    mock_session.sync_document = MagicMock()

    with patch.object(lsp_api, "_open_file_session", return_value=(mock_session, "file:///f.py")):
        result = lsp_api.completion("src/f.py", "5:1", limit=10)
    assert len(result) == 10
```

---

## Files

| File | Change |
|------|--------|
| `src/audiagentic/components/coding_lsp/lsp_lifecycle.py` | Add `typeHierarchyProvider` to map; add `inlay_hints`, `signature_help`, `type_hierarchy_prepare`, `type_hierarchy_supertypes`, `type_hierarchy_subtypes`, `completion` methods |
| `src/audiagentic/components/coding_lsp/lsp_api.py` | Add 4 normalize helpers; add `inlay_hints`, `signature_help`, `type_hierarchy`, `completion` API functions |
| `src/audiagentic/components/coding_lsp/lsp_mcp.py` | Register `lsp_inlay_hints`, `lsp_signature_help`, `lsp_type_hierarchy`, `lsp_completion` |
| `tests/unit/coding_lsp/test_lsp_lifecycle.py` | 6 new tests |
| `tests/unit/coding_lsp/test_lsp_api.py` | 3 new tests |

## Validation

```
pytest tests/unit/coding_lsp/ -x -q
```

- Each method returns `[]` / `None` when `has_capability` is false (never hangs).
- `completion` unwraps `CompletionList` wrapper correctly.
- `inlay_hints` label parts (list of `{value}` objects) join to a string.
- `type_hierarchy` two-phase (prepare → supertypes/subtypes) is exercised.
- `lsp_capabilities` now lists `inlayHint`, `signatureHelp`, `typeHierarchy`,
  `completion` for servers that advertise them.

## Effort & Risk

Mid. All four are read-only and capability-gated. Lowest individual risk in this plan.
Type hierarchy has a two-phase API (prepare + resolve) which requires two round trips.

## Dependencies

CAP01 (routing). CAP02 adds `typeHierarchyProvider` to the map — if done first, skip
Step 1 here.

## Notes

- `lsp_completion` returns at most `limit` (default 20) items for agent usability.
  Do not raise the default — completion lists commonly contain 500+ items.
- `lsp_type_hierarchy` returns an empty list for Python (pyright has partial support,
  clangd and rust-analyzer fully support it). The CAP06 matrix will document per-server
  actual support.
- Inlay hints may be slow on large files. The `start`/`end` range bounds the request.
