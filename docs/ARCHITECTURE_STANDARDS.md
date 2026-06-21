# AUDiaGentic Architecture Standards

Non-negotiable rules. Violations are architectural defects, not style issues.

## 1. Layer Boundaries

```
CLI / composition root
Components  -->  Runtime  -->  Foundation
```

- **CLI / composition root** (`audiagentic/launcher.py`, `audiagentic/commands/*`) — wires the application together. May import any layer, including specific optional components. This is the only layer permitted to.
- **Foundation** — shared primitives. Zero imports from runtime or components.
- **Runtime** — lifecycle, config, harness, state. May import foundation only.
- **Components** — product capabilities. May import runtime and foundation.

**Rules:**
- Foundation must never import from runtime. If a utility lives in runtime but is needed by foundation, move it to foundation.
- Runtime must never import from a specific optional component. Use registered callbacks, events, or contribution registries.
- The import-down prohibition applies to `foundation/` and `runtime/`, **not** to the composition root. Composition roots are exempt from layering rules by definition.

## 2. Config Over Code

Extensibility must never require editing Python source.

**Rules:**
- Lists of entities (components, providers, tools, states, policies, capabilities) must be declared in YAML/JSON — never hardcoded in Python.
- `if/elif` chains that branch on entity names (component ID, provider name, action tag, file path) are prohibited. Use a registry of `(key, handler)` pairs or a config-driven lookup table.
- Adding a new capability = dropping a config file or registering a callback. No Python edits.

## 3. Logic Containment

**Rules:**
- Shared logic (2+ files) → extract to foundation immediately.
- God objects (>350 lines, >3 responsibilities) → decompose if responsibilities are logically split and can be sensibly decomposed by concern. Exceptions are allowable for sensible containment of logic
- Duplicate dataclasses (>80% field overlap) → unify to one canonical type.

## 4. Platform Independence

**Rules:**
- Never reference a specific editor's CLI, binary, or filesystem paths. Abstract to a pluggable host adapter.
- Host-specific behavior (extension installation, workspace detection) → resolved at runtime through a config-driven adapter.

## 5. Component Discovery

**Rules:**
- Never maintain a Python import list or `__all__` that enumerates pluggable modules. Use `pkgutil.iter_modules()` or config-driven discovery.
- Component IDs derived from loaded descriptors — not maintained as parallel Python constants.

## 6. MCP Server Construction

**Rules:**
- Use `mcp_server(__name__)` from `foundation.mcp.component_server`. Never construct `FastMCP` manually.
- Use `run_mcp_server(server_factory, label)` for `main()`. Never duplicate the bootstrap pattern.

## 7. Virtual Assets

**Rules:**
- Generated files → registry of `(path_pattern, generator_fn)` pairs. Components register their own generators via lifecycle hooks.
- Runtime iterates the registry; it never branches on asset paths.

## 8. Error Handling

**Rules:**
- `AudiaGenticError` is the only domain exception. No parallel hierarchies (`EventBusError`, `LspError`). No raw `ValueError`/`RuntimeError` at public boundaries.
- Every error must carry a canonical code: `PREFIX-COMPONENT-NNN` (e.g., `VAL-PCFG-001`).
- Prefer `make_error()` from `foundation.contracts.errors` for construction.
- `except Exception:` only at external boundaries (I/O, subprocess, network, third-party). Internal code catches specific types.
- Every `except` block must: (a) log with `exc_info=True`, (b) wrap as `AudiaGenticError`, or (c) return a safe default. Silent `pass` only in teardown where exception is expected and harmless.
- Error details must never include raw stdout/stderr, API keys, tokens, or user prompts. Redact or summarize.

## 9. Logging

**Rules:**
- Module-level logger only: `logger = logging.getLogger(__name__)` at module scope. Never inline.
- `print()` only in CLI entry points. All library code → `logger`.
- Log levels: `debug` (trace), `info` (notable ops), `warning` (non-fatal — always `exc_info=True`), `error` (failures — always `exc_info=True`).
- Entity-referencing messages must carry `extra={"component": ..., "provider": ..., "item_id": ...}`.
- MCP tool args must never be logged.

## 10. Anti-Pattern Quick Reference

| Anti-pattern | Fix |
|---|---|
| Hardcoded list of entities | Config-driven or registry |
| `if x == "a": ... elif x == "b":` on entity names | `(key, handler)` registry |
| `foundation/` imports `components/` or `runtime/` | Move utility to foundation |
| `runtime/` imports optional component internals | Events, callbacks, contribution registry |
| Manual `FastMCP(...)` construction | `mcp_server(__name__)` |
| `raise ValueError("...")` at public boundary | `AudiaGenticError(code=..., ...)` |
| `except Exception: pass` | Log `exc_info=True`, wrap, or safe default |
| `logging.getLogger(__name__).warning(...)` inline | Module-level `logger` |
| `print(...)` in library code | `logger.info/debug/warning/error` |
| Raw stdout/stderr in error details | Redact or summarize |
| `__all__ = ["aider", "claude", ...]` | `pkgutil.iter_modules()` discovery |
| Hardcoded editor CLI/paths | Pluggable host adapter |
