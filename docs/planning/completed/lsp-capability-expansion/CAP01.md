---
id: CAP01
order: 1
plan: plan-lsp-capability-expansion
state: done
validate-first: true
priority: P1
complexity: complex
---

# Multi-server-per-language foundation

## Description

Today one language maps to exactly one LSP server. `resolve_active_runtime_servers`
returns `dict[language → ServerConfig]` and dedupes by language at
[runtime_resolver.py:60](../../../../src/audiagentic/components/coding_lsp/runtime_resolver.py#L60)
(`if language in servers: continue`).
`SessionManager` keys sessions by `language: str` as the inner dict key.

This blocks pyright + ruff coexistence for Python (and any other language wanting
a semantic + lint companion). Goal: N servers per language, with capability-routed
selection — navigation tools use the first capable server; diagnostics merge all.

---

## Exact implementation steps (sequential)

### Step 1 — Add `server_id` field to `ServerConfig`

**File:** `src/audiagentic/components/coding_lsp/lsp_lifecycle.py`

Locate the `ServerConfig` dataclass (currently at line 53). Add `server_id: str = ""`
as the last field:

```python
@dataclass
class ServerConfig:
    """Configuration for a single language server."""
    command: list[str]
    file_extensions: list[str] = field(default_factory=list)
    workspace_config_files: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    label: str = ""
    server_id: str = ""   # stable id: dep id from the language YAML
```

No other changes to `lsp_lifecycle.py` for this step.

---

### Step 2 — Change resolver to return `dict[str, list[ServerConfig]]`

**File:** `src/audiagentic/components/coding_lsp/runtime_resolver.py`

Replace the entire `resolve_active_runtime_servers` function (currently lines 56-76):

```python
def resolve_active_runtime_servers(project_root: Path) -> dict[str, list[ServerConfig]]:
    """Return all active server configs per language, ordered (semantic server first).

    Returns dict[language → list[ServerConfig]] where each ServerConfig has
    server_id set to the dependency id from the language YAML. Multiple entries
    per language are possible when >1 server feature is active for that language.
    """
    servers: dict[str, list[ServerConfig]] = {}
    for binding in active_language_bindings(project_root):
        language = binding.feature
        spec = language_registry.get_language(language)
        if spec is None:
            continue
        state = get_feature_state(project_root, COMPONENT_CODING_LSP, "language", language)
        server_settings = state.options.get("server-settings", {})
        if not isinstance(server_settings, dict):
            server_settings = {}
        dep_id = spec.dependency.id if spec.dependency is not None else spec.id
        cfg = ServerConfig(
            command=list(spec.command),
            file_extensions=list(spec.file_extensions),
            workspace_config_files=list(spec.workspace_config_files),
            settings={**dict(spec.settings), **server_settings},
            label=spec.display_name,
            server_id=dep_id,
        )
        # Avoid exact duplicate servers (same dep_id for same language)
        existing_ids = {s.server_id for s in servers.get(language, [])}
        if dep_id not in existing_ids:
            servers.setdefault(language, []).append(cfg)
    return servers
```

**Important:** The return type annotation changes from `dict[str, ServerConfig]` to
`dict[str, list[ServerConfig]]`. All callers must be updated in subsequent steps.

---

### Step 3 — Update `SessionManager` to key sessions by `(language, server_id)`

**File:** `src/audiagentic/components/coding_lsp/lsp_session_manager.py`

The inner session dict changes its key from bare `language: str` to a compound
`session_key: str` = `f"{language}:{server_id}"`. The outer structure stays
`dict[root_key, dict[session_key, LspSession]]`.

**3a.** Add a helper method at the bottom of `SessionManager`:

```python
@staticmethod
def _session_key(language: str, server_config: ServerConfig) -> str:
    sid = server_config.server_id or (server_config.command[0] if server_config.command else "unknown")
    return f"{language}:{sid}"
```

**3b.** Update `get_or_create`:

```python
def get_or_create(
    self, project_root: str | Path, language: str, server_config: ServerConfig,
) -> LspSession:
    root_key = str(Path(project_root).resolve())
    self._ensure_dir(root_key)
    sk = self._session_key(language, server_config)

    if sk in self._sessions[root_key]:
        session = self._sessions[root_key][sk]
        self._touch(root_key, sk)
        if session.is_ready():
            return session
        session.shutdown()

    session = LspSession(server_config, project_root)
    session.initialize()
    session.initialized()
    self._sessions[root_key][sk] = session
    self._touch(root_key, sk)
    return session
```

**3c.** Update `shutdown_session` — add `server_id: str = ""` parameter:

```python
def shutdown_session(
    self, project_root: str | Path, language: str, server_id: str = "",
) -> None:
    """Shut down a specific language session.

    If server_id is given, shuts down only that server's session.
    If server_id is empty, shuts down ALL sessions for the language.
    """
    root_key = str(Path(project_root).resolve())
    lang_sessions = self._sessions.get(root_key, {})
    to_remove = []
    for sk, session in lang_sessions.items():
        lang_part, _, sid_part = sk.partition(":")
        if lang_part == language and (not server_id or sid_part == server_id):
            session.shutdown()
            to_remove.append(sk)
    for sk in to_remove:
        lang_sessions.pop(sk, None)
        self._last_used.get(root_key, {}).pop(sk, None)
```

**3d.** Update `status` — expose `server_id` in each entry:

```python
def status(self) -> dict[str, Any]:
    roots: dict[str, list[dict[str, Any]]] = {}
    for root_key, sessions in self._sessions.items():
        root_status: list[dict[str, Any]] = []
        for sk, session in sessions.items():
            language, _, server_id = sk.partition(":")
            last = self._last_used.get(root_key, {}).get(sk, 0)
            root_status.append({
                "language": language,
                "server_id": server_id,
                "ready": session.is_ready(),
                "last_used_ago_s": round(time.monotonic() - last, 1),
                "server": session.server_config.command[0] if session.server_config.command else "unknown",
            })
        roots[root_key] = root_status
    return {
        "project_roots": len(roots),
        "total_sessions": sum(len(v) for v in roots.values()),
        "roots": roots,
    }
```

**3e.** Update `idle_check` — uses `sk` directly (already works; no language-string lookups):

```python
def idle_check(self, timeout: float | None = None) -> list[str]:
    if timeout is None:
        timeout = _DEFAULT_IDLE_TIMEOUT
    now = time.monotonic()
    shutdown: list[str] = []
    for root_key in list(self._sessions.keys()):
        for sk in list(self._sessions[root_key].keys()):
            last = self._last_used.get(root_key, {}).get(sk, 0)
            if now - last > timeout:
                self._sessions[root_key][sk].shutdown()
                del self._sessions[root_key][sk]
                self._last_used.get(root_key, {}).pop(sk, None)
                shutdown.append(f"{root_key}/{sk}")
    for root_key in list(self._sessions.keys()):
        if not self._sessions[root_key]:
            del self._sessions[root_key]
            self._last_used.pop(root_key, None)
    return shutdown
```

**3f.** Update `_touch` — already uses arbitrary string key; no change needed if the
old calls used `language` — change every `_touch(root_key, language)` call to use
`sk` in `get_or_create` (done above in 3b).

**3g.** Update `diagnostics` — iterate all sessions under root (the `.values()` loop
already works since keys changed):

```python
def diagnostics(
    self, project_root: str | Path, *, min_severity: int = 4, limit: int = 0,
    force_refresh: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    root_key = str(Path(project_root).resolve())
    cache_key = f"{root_key}:{min_severity}:{limit}"

    if not force_refresh:
        cached = self._diagnostics_cache.get(cache_key)
        if cached:
            ts, data = cached
            if time.monotonic() - ts < _DIAGNOSTICS_CACHE_TTL:
                return data

    all_diagnostics: dict[str, list[dict[str, Any]]] = {}
    for session in self._sessions.get(root_key, {}).values():
        # Merge: each session contributes its own URIs; overlapping URIs union
        for uri, diags in session.diagnostics(min_severity=min_severity, limit=limit).items():
            existing = all_diagnostics.setdefault(uri, [])
            # De-duplicate by (range, code, source, message)
            existing_keys = {
                (d.get("source"), d.get("code"), str(d.get("range", {})), d.get("message", "")[:80])
                for d in existing
            }
            for d in diags:
                key = (d.get("source"), d.get("code"), str(d.get("range", {})), d.get("message", "")[:80])
                if key not in existing_keys:
                    existing.append(d)
                    existing_keys.add(key)

    self._diagnostics_cache[cache_key] = (time.monotonic(), all_diagnostics)
    return all_diagnostics
```

---

### Step 4 — Update `lsp_api.py` to use `list[ServerConfig]`

**File:** `src/audiagentic/components/coding_lsp/lsp_api.py`

**4a.** Add two helpers after the existing `discover_servers` function (currently at
line 212):

```python
def _resolve_language_servers_for_file(
    file_path: Path, project_root: Path,
) -> list[tuple[str, "ServerConfig"]]:
    """Return all (language, server) pairs that handle this file.

    Ordered: semantic server first per language (resolver order is preserved).
    Auto-enables the language if it's not yet enabled but the extension matches.
    """
    from audiagentic.components.coding_lsp import language_registry as _lr
    from audiagentic.foundation.components.ids import COMPONENT_CODING_LSP
    from audiagentic.foundation.features.base import FeatureState
    from audiagentic.foundation.features.state import (
        get_feature_state,
        set_feature_state,
    )
    from audiagentic.components.coding_lsp.coding_lsp_config import (
        resolve_server_for_file as _resolve_one,
    )

    servers_by_lang = discover_servers_multi(project_root)
    ext = file_path.suffix.lower()
    matches: list[tuple[str, Any]] = []

    for language, cfgs in servers_by_lang.items():
        for cfg in cfgs:
            if ext in cfg.file_extensions:
                matches.append((language, cfg))

    if not matches:
        # Auto-enable language that covers this extension
        for lang_id, spec in _lr.all_languages().items():
            if ext in spec.file_extensions and lang_id not in servers_by_lang:
                state = get_feature_state(project_root, COMPONENT_CODING_LSP, "language", lang_id)
                if not state.enabled:
                    set_feature_state(
                        project_root, COMPONENT_CODING_LSP, "language", lang_id,
                        FeatureState(enabled=True, options=dict(state.options)),
                    )
                    servers_by_lang = discover_servers_multi(project_root)
                    for cfg in servers_by_lang.get(lang_id, []):
                        if ext in cfg.file_extensions:
                            matches.append((lang_id, cfg))

    return matches


def discover_servers_multi(project_root: str | Path) -> dict[str, list["ServerConfig"]]:
    """Return dict[language → list[ServerConfig]] for the resolved project root."""
    resolved_root = resolve_project_root(project_root)
    return resolve_active_runtime_servers(resolved_root)


def pick_capable(
    project_root: Path, file_path: Path, method: str,
) -> "LspSession | None":
    """Return the first session (for this file's language) that supports method.

    Creates/warms all sessions for the file before checking capability.
    Returns None if no server supports the method.
    """
    for language, cfg in _resolve_language_servers_for_file(file_path, project_root):
        session = _session_manager.get_or_create(project_root, language, cfg)
        if session.has_capability(method):
            return session
    return None


def all_sessions_for_file(
    project_root: Path, file_path: Path,
) -> list["LspSession"]:
    """Return all warmed sessions that handle this file (across all servers)."""
    sessions = []
    for language, cfg in _resolve_language_servers_for_file(file_path, project_root):
        sessions.append(_session_manager.get_or_create(project_root, language, cfg))
    return sessions
```

**4b.** Add `from audiagentic.components.coding_lsp.lsp_lifecycle import LspSession` at the
top-of-file imports (it was previously only imported via `lsp_session_manager`). Add it
next to the existing `from audiagentic.components.coding_lsp.lsp_session_manager import SessionManager`.

**4c.** Update the existing `discover_servers` function (currently line 212) to delegate:

```python
def discover_servers(project_root: str | Path) -> dict[str, Any]:
    """Backward-compat wrapper: returns first server per language (single-server view)."""
    resolved_root = resolve_project_root(project_root)
    multi = resolve_active_runtime_servers(resolved_root)
    return {lang: cfgs[0] for lang, cfgs in multi.items() if cfgs}
```

**4d.** Update `_open_file_session` — replace the single-server lookup with
`pick_capable` for the method passed in:

```python
def _open_file_session(file: str, method: str = "") -> tuple[Any, str]:
    """Return (session, uri) for the best server for file+method.

    If method is given, picks the first server advertising it.
    Falls back to the first available server if no capability match.
    """
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    language_servers = _resolve_language_servers_for_file(file_path, project_root)
    if not language_servers:
        return {"error": f"No language server for {file}"}, file_to_uri(file_path)

    uri = file_to_uri(file_path)
    text = file_path.read_text(encoding="utf-8", errors="replace")

    # Warm all sessions; pick capable for the requested method
    sessions_for_method: list[Any] = []
    fallback: Any = None
    for language, cfg in language_servers:
        session = _session_manager.get_or_create(project_root, language, cfg)
        session.sync_document(uri, text, _lang_to_id(language))
        if fallback is None:
            fallback = session
        if method and session.has_capability(method):
            sessions_for_method.append(session)

    chosen = sessions_for_method[0] if sessions_for_method else fallback
    return chosen, uri
```

**4e.** Update every caller of `_open_file_session` to pass the method name.

Go through `lsp_api.py` and add the method argument to each call:

| Function | Call to update | Method string |
|---|---|---|
| `document_symbols` | `_open_file_session(file)` | `"textDocument/documentSymbol"` |
| `definition` | `_open_file_session(file)` | `"textDocument/definition"` |
| `hover` | `_open_file_session(file)` | `"textDocument/hover"` |
| `references` | `_open_file_session(file)` | `"textDocument/references"` |
| `type_definition` | `_open_file_session(file)` | `"textDocument/typeDefinition"` |
| `implementation` | `_open_file_session(file)` | `"textDocument/implementation"` |
| `call_hierarchy` | `_open_file_session(file)` | `"textDocument/callHierarchy"` |
| `symbol_context` | `_open_file_session(file)` | `"textDocument/hover"` |
| `code_actions` | `_open_file_session(file)` | `"textDocument/codeAction"` |
| `format_preview` | `_open_file_session(file)` | `"textDocument/formatting"` |
| `organize_imports_preview` | `_open_file_session(file)` | `"textDocument/codeAction"` |
| `rename_preview` | `_open_file_session(file)` | `"textDocument/rename"` |
| `server_capabilities` | (uses `_resolve_language_server`, see below) | — |

**4f.** Update `diagnostics` (the workspace-level function, currently line 408):

```python
def diagnostics(
    root: str = ".", min_severity: int = 4, limit: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    project_root = resolve_project_root(root)
    for language, servers in resolve_active_runtime_servers(project_root).items():
        for cfg in servers:
            _session_manager.get_or_create(project_root, language, cfg)
    return _session_manager.diagnostics(project_root, min_severity=min_severity, limit=limit)
```

**4g.** Update `file_diagnostics` to gather results from all matching sessions:

```python
def file_diagnostics(
    file: str, min_severity: int = 4, timeout: float = 5.0,
) -> list[dict[str, Any]]:
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    language_servers = _resolve_language_servers_for_file(file_path, project_root)
    if not language_servers:
        return [{"source": "coding-lsp", "severity": 1, "code": "EXT-LSP-007",
                  "message": f"No configured language server for {file}",
                  "file": str(file_path),
                  "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}}]

    uri = file_to_uri(file_path)
    merged: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for language, cfg in language_servers:
        session = _session_manager.get_or_create(project_root, language, cfg)
        for d in session.file_diagnostics(uri, min_severity=min_severity, timeout=timeout):
            key = (d.get("source"), d.get("code"), str(d.get("range", {})), d.get("message", "")[:80])
            if key not in seen:
                merged.append(d)
                seen.add(key)
    return merged
```

**4h.** Update `server_capabilities` to report per-server results:

```python
def server_capabilities(file: str) -> dict[str, Any]:
    file_path = Path(file).resolve()
    project_root = resolve_project_root(file_path)
    language_servers = _resolve_language_servers_for_file(file_path, project_root)
    if not language_servers:
        return {"error": f"No language server for {file}", "supported": []}

    method_labels = {
        "textDocument/definition": "definition",
        "textDocument/hover": "hover",
        "textDocument/references": "references",
        "textDocument/rename": "rename",
        "textDocument/documentSymbol": "documentSymbol",
        "textDocument/typeDefinition": "typeDefinition",
        "textDocument/implementation": "implementation",
        "textDocument/codeAction": "codeAction",
        "textDocument/formatting": "formatting",
        "textDocument/rangeFormatting": "rangeFormatting",
        "textDocument/completion": "completion",
        "textDocument/signatureHelp": "signatureHelp",
        "textDocument/inlayHint": "inlayHint",
        "textDocument/callHierarchy": "callHierarchy",
        "workspace/symbol": "workspaceSymbol",
        "workspace/diagnostic": "workspaceDiagnostic",
    }

    servers_out: list[dict[str, Any]] = []
    all_supported: set[str] = set()
    language = language_servers[0][0]

    for lang, cfg in language_servers:
        session = _session_manager.get_or_create(project_root, lang, cfg)
        caps = session.capabilities()
        supported = [label for method, label in method_labels.items() if session.has_capability(method)]
        all_supported.update(supported)
        servers_out.append({
            "server_id": cfg.server_id,
            "label": cfg.label,
            "supported": supported,
            "raw": caps,
        })

    return {
        "language": language,
        "servers": servers_out,
        "supported": sorted(all_supported),  # union across all servers
    }
```

**4i.** Remove the old `_resolve_language_server` function entirely (lines 527-559).
It is replaced by `_resolve_language_servers_for_file`.

**4j.** Update `workspace_symbols` to iterate the new multi-server structure:

```python
def workspace_symbols(query: str, root: str = ".") -> list[dict[str, Any]]:
    project_root = resolve_project_root(root)
    servers = discover_servers_multi(project_root)
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for language, cfgs in servers.items():
        for cfg in cfgs:
            try:
                session = _session_manager.get_or_create(project_root, language, cfg)
                # Only call workspace_symbol on servers that support it
                if not session.has_capability("workspace/symbol"):
                    continue
                raw = session.workspace_symbol(query)
                for s in raw:
                    results.append(normalize_symbol(s, project_root))
            except Exception as exc:
                results.append({"error": f"{language}/{cfg.server_id}: {exc}"})
    return results
```

---

### Step 5 — Update `coding_lsp_config.py` callers

**File:** `src/audiagentic/components/coding_lsp/coding_lsp_config.py`

`discover_language_servers` (line 144) currently iterates `servers` as `dict[str, ServerConfig]`.
Update it for `dict[str, list[ServerConfig]]`:

```python
def discover_language_servers(project_root: Path | str) -> dict[str, bool]:
    project_root = _as_path(project_root)
    from audiagentic.components.coding_lsp.runtime_resolver import resolve_active_runtime_servers
    servers = resolve_active_runtime_servers(project_root)

    results: dict[str, bool] = {}
    for language, cfgs in servers.items():
        # Report True if ANY server for this language is available
        lang = language_registry.get_language(language)
        if lang is not None and lang.dependency is not None:
            probe = build_dependency_probes({lang.dependency.id: lang.dependency.cfg})
            results[language] = probe[lang.dependency.id]()
        else:
            # Fallback: check first server's binary
            first_cmd = cfgs[0].command if cfgs else []
            results[language] = bool(first_cmd) and shutil.which(first_cmd[0]) is not None
    return results
```

Also update `resolve_server_for_file` to accept the new multi-server type:

```python
def resolve_server_for_file(
    file_path: Path | str,
    servers: dict[str, "ServerConfig"] | dict[str, list["ServerConfig"]],
) -> "ServerConfig | None":
    """Find a language server that handles a given file extension.

    Accepts both old single-server dict and new multi-server dict shapes.
    """
    file_path = _as_path(file_path)
    ext = file_path.suffix.lower()
    for value in servers.values():
        if isinstance(value, list):
            for cfg in value:
                if ext in cfg.file_extensions:
                    return cfg
        else:
            if ext in value.file_extensions:
                return value
    return None
```

---

### Step 6 — Update other callers of the old `resolve_active_runtime_servers`

Search for all remaining references to the old single-server return shape:

```
grep -rn "resolve_active_runtime_servers" src/
```

Typical patterns to fix:

**Pattern A** — `for language, server in resolve_active_runtime_servers(...).items():`
→ change to `for language, servers in ...: for server in servers:`

**Pattern B** — `servers[language]` (dict lookup expecting `ServerConfig`)
→ change to `servers.get(language, [None])[0]` or iterate

Check these files:
- `src/audiagentic/components/coding_lsp/language_servers_sync.py`
- `src/audiagentic/components/providers/services/lsp_projection.py`
- `src/audiagentic/components/providers/services/mcp_projection.py`

For each, wrap the inner value in a `for cfg in cfgs:` loop or take `cfgs[0]`
if only one server per language was expected.

---

### Step 7 — Fix existing tests

**File:** `tests/unit/coding_lsp/test_session_manager.py`

The `shutdown_session` tests call `mgr.shutdown_session("/tmp", "python")` — this
still works (no `server_id` given → shuts down all sessions for `python`).

The `get_or_create` tests pass `ServerConfig(command=..., label="python")` — they
need `server_id` set for the key to be deterministic. Update `_python_config()`:

```python
def _python_config() -> ServerConfig:
    return ServerConfig(
        command=["pyright-langserver", "--stdio"],
        file_extensions=[".py", ".pyi"],
        label="python",
        server_id="pyright",
    )
```

**File:** `tests/unit/coding_lsp/test_runtime_resolver.py`

Any test that does `assert isinstance(result, dict)` and then accesses `result["python"]`
as a `ServerConfig` needs updating. The value is now `list[ServerConfig]`, so:
- `result["python"]` → `result["python"][0]` where a single server was expected
- Add a test that verifies list return type

**File:** `tests/unit/coding_lsp/test_lsp_api.py`

Tests that call `discover_servers` via mock and expect `{language: ServerConfig}`
need updating to return `{language: [ServerConfig]}` from the mock.

---

### Step 8 — Add new multi-server tests

**File:** `tests/unit/coding_lsp/test_session_manager.py`

Add:

```python
def test_two_servers_same_language_create_two_sessions() -> None:
    mgr = SessionManager()
    cfg1 = ServerConfig(command=["server-a"], file_extensions=[".py"], server_id="a")
    cfg2 = ServerConfig(command=["server-b"], file_extensions=[".py"], server_id="b")
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", cfg1)
        mgr.get_or_create("/tmp", "python", cfg2)
        assert MockSession.call_count == 2
        assert mgr.status()["total_sessions"] == 2


def test_shutdown_session_by_server_id() -> None:
    mgr = SessionManager()
    cfg1 = ServerConfig(command=["server-a"], file_extensions=[".py"], server_id="a")
    cfg2 = ServerConfig(command=["server-b"], file_extensions=[".py"], server_id="b")
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock = MagicMock()
        mock.is_ready.return_value = True
        MockSession.return_value = mock
        mgr.get_or_create("/tmp", "python", cfg1)
        mgr.get_or_create("/tmp", "python", cfg2)
        mgr.shutdown_session("/tmp", "python", server_id="a")
        assert mgr.status()["total_sessions"] == 1


def test_diagnostics_merge_deduplicates() -> None:
    mgr = SessionManager()
    diag = {"source": "pyright", "code": "E001", "range": {}, "message": "err", "severity": 1}
    with patch("audiagentic.components.coding_lsp.lsp_session_manager.LspSession") as MockSession:
        mock1 = MagicMock()
        mock1.is_ready.return_value = True
        mock1.diagnostics.return_value = {"file:///f.py": [diag]}
        MockSession.return_value = mock1
        mgr.get_or_create("/tmp", "python", ServerConfig(command=["a"], server_id="a"))
        mock2 = MagicMock()
        mock2.is_ready.return_value = True
        mock2.diagnostics.return_value = {"file:///f.py": [diag]}  # same diag
        mgr._sessions[str(Path("/tmp").resolve())]["python:b"] = mock2
        result = mgr.diagnostics("/tmp")
        assert len(result.get("file:///f.py", [])) == 1  # deduped
```

---

## Files

| File | Change type |
|------|------------|
| `src/audiagentic/components/coding_lsp/lsp_lifecycle.py` | Add `server_id` field to `ServerConfig` |
| `src/audiagentic/components/coding_lsp/runtime_resolver.py` | Return `dict[str, list[ServerConfig]]` |
| `src/audiagentic/components/coding_lsp/lsp_session_manager.py` | Key by `(language, server_id)`; merge diagnostics; update all methods |
| `src/audiagentic/components/coding_lsp/lsp_api.py` | `discover_servers_multi`, `pick_capable`, `all_sessions_for_file`; update all callers |
| `src/audiagentic/components/coding_lsp/coding_lsp_config.py` | Update `discover_language_servers`, `resolve_server_for_file` |
| `src/audiagentic/components/coding_lsp/language_servers_sync.py` | Update callers (pattern A fix) |
| `src/audiagentic/components/providers/services/lsp_projection.py` | Update callers |
| `src/audiagentic/components/providers/services/mcp_projection.py` | Update callers |
| `tests/unit/coding_lsp/test_session_manager.py` | Fix `_python_config()`, add 3 new tests |
| `tests/unit/coding_lsp/test_runtime_resolver.py` | Fix assertions for list return type |
| `tests/unit/coding_lsp/test_lsp_api.py` | Fix mocks for multi-server shape |

## Validation

Run after each step to catch regressions early:
```
pytest tests/unit/coding_lsp/ -x -q
```

Full check after all steps:
```
pytest tests/ -x -q --ignore=tests/integration
```

Two servers for Python → two distinct sessions in `status()`. Navigation routes to
the server advertising the method (pyright for definition, ruff for formatting).
Diagnostics merge both. Single-server languages (rust, ts, cpp) behave identically.
Idle-check and shutdown operate per `(language, server_id)`. All existing tests pass.

## Effort & Risk

High. Touches the session key used across all tools. Take the steps in order;
run tests between steps. The `discover_servers` backward-compat wrapper (step 4c)
lets unaudited callers keep working while you fix them.

## Dependencies

None (foundation item).

## Notes

- `server_id` is set from the dependency `id` in the YAML (e.g. `pyright`, `ruff`).
  If a server has no dependency block (unusual), fall back to the command basename.
- Do NOT delete `discover_servers` (the old single-server function) until CAP03 lands
  and all callers have been audited — use it as a temporary shim.
- The dedup in `diagnostics` uses a 4-tuple key. If two servers report the same
  diagnostic with the same rule code and range, only one copy is kept.
