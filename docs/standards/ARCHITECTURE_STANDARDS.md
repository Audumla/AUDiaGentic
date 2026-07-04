# AUDiaGentic Architecture Standards

Non-negotiable rules. Violations are architectural defects, not style issues.

## 1. Layer Boundaries

```
CLI / composition root
Components  --consume-->  Foundation (capabilities)  --may read-->  Runtime environment
Runtime (orchestration)  --bootstraps/wires via seams-->  foundation capabilities
```

- **CLI / composition root** (`audiagentic/launcher.py`, `audiagentic/commands/*`) — wires the app together. May import any layer, including specific optional components. The only layer permitted to.
- **Components** — product capabilities. May import foundation and runtime.
- **Foundation** — the capability layer, not a "bottom" layer. Provides shared capabilities (errors, events, IO, toolchains, workflow, MCP plumbing, component lifecycle — `foundation/lifecycle`) to components and the CLI. A capability may read the runtime environment to adapt its behavior (e.g. platform-dependent tool selection).
- **Runtime environment** (`runtime/system`) — read-only facts about the live execution context: platform, process identity, live paths. Importable from any layer, including foundation.
- **Runtime orchestration** (`runtime/harness`, `runtime/rig`, `runtime/update`, `runtime/build`) — bootstrap, lifecycle transitions, durable state. Acts as a quasi-composition root: calling foundation capabilities while bootstrapping is expected and normal. After startup, runtime should have limited need to call foundation capabilities directly — prefer events, callbacks, and registries. This is guidance, not a hard rule; the bootstrap boundary is inherently fuzzy.

**Rules:**
- Foundation must never import runtime orchestration or components. It may import the runtime environment namespace (`runtime/system`) freely — that is the sanctioned "capability reads environment" seam.
- Environment modules (`runtime/system`) hold read-only facts only: no orchestration logic, no imports from foundation, components, or the rest of runtime.
- Runtime must never import a specific optional component. Use registered callbacks, events, or contribution registries.
- Composition roots are exempt from import-direction rules by definition.

## 2. Config Over Code

Extensibility must never require editing Python source.

**Rules:**
- Lists of entities (components, providers, tools, states, policies, capabilities) must be declared in YAML/JSON — never hardcoded in Python.
- `if/elif` chains that branch on entity names (component ID, provider name, action tag, file path) are prohibited. Use a registry of `(key, handler)` pairs or a config-driven lookup table.
- Adding a new capability = dropping a config file or registering a callback. No Python edits.

## 3. Logic Containment

**Rules:**
- Shared logic (2+ files) → extract to foundation immediately.
- God objects (>350 lines, >3 responsibilities) → decompose by concern, unless the logic is genuinely one cohesive unit.
- Duplicate dataclasses (>80% field overlap) → unify to one canonical type.

## 4. Platform Independence

**Rules:**
- Never reference a specific editor's CLI, binary, or filesystem paths. Abstract to a pluggable host adapter.
- Host-specific behavior (extension installation, workspace detection) → resolved at runtime through a config-driven adapter.
- Never embed local folder names or local network or local environment details in code. Where necessary any local environment information must be maintained in non git committed config or env files.

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
- Error ownership is split intentionally:
  - `code` is canonical identity and must be stable.
  - `message` is the concise operator-facing statement raised by code and returned in the error envelope.
  - `resolution` is optional agent/operator guidance and belongs in config (`error-resolutions.yaml`).
  - `details` carries contextual diagnostics only; never use it as the primary message channel.
- `error-resolutions.yaml` is for remediation/help text only. It must not be treated as the canonical source of the raised `message`.
- If a component needs config-driven canonical messages in the future, use a separate dedicated registry/file; do not overload `error-resolutions.yaml` with two meanings.
- Prefer `make_error()` from `foundation.contracts.errors` for construction.
- Prefer a module-local bound factory (`make_error_factory(...)`) or thin helper so one module does not hand-inline dozens of `AudiaGenticError(...)` strings/code tuples.
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

## 10. Migration Doctrine

**Rules:**
- **No backward compatibility shims** — unless explicitly stated, we do not maintain backward compatibility. Migrate code as we refactor. Always.
- **No legacy code left behind** — do not create shim functions, deprecation warnings, or parallel paths. Remove legacy code in the same change that introduces the replacement.
- **Atomic migration** — each migration step must leave the system in a working state. Never pass through a broken intermediate state.
- **Test-driven migration** — add or update tests alongside the migration. Do not defer testing.

## 11. Lazy Initialization

**Rules:**
- Prefer lazy, on-first-access loading over eager centralized bootstrap for config-driven registries and shared state. A module that needs a registry populated may call its loader defensively from wherever it needs the data — this is the intended pattern, not duplication to be cleaned up.
- A loader function called this way must be safe **and cheap** to call repeatedly: idempotent (re-registering unchanged state is a no-op) *and* internally cached/short-circuited on unchanged inputs. "Idempotent" alone (safe but re-does the work every time) is not sufficient once a function has more than a couple of call sites.
- If repeated calls turn out to be expensive, fix the cost inside the loader (cache/short-circuit keyed on its inputs) — do not "fix" it by centralizing or reducing the number of call sites. Scattered lazy self-bootstrap is not an anti-pattern here.
- When building a registry that needs on-first-access population, prefer composing the shared registry utility's built-in lazy-loader support over hand-rolling a module-level `_loaded`/`_ensure_loaded()` guard.

## 12. Anti-Pattern Quick Reference

| Anti-pattern | Fix |
|---|---|
| Hardcoded list of entities | Config-driven or registry |
| `if x == "a": ... elif x == "b":` on entity names | `(key, handler)` registry |
| `foundation/` imports `components/` or runtime orchestration (anything outside `runtime/system`) | Invert via capability registry/events, or move the fact into `runtime/system` |
| Orchestration logic or upward imports inside `runtime/system` | Environment modules hold read-only facts only |
| `runtime/` imports optional component internals | Events, callbacks, contribution registry |
| Manual `FastMCP(...)` construction | `mcp_server(__name__)` |
| `raise ValueError("...")` at public boundary | `AudiaGenticError(code=..., ...)` |
| `except Exception: pass` | Log `exc_info=True`, wrap, or safe default |
| `logging.getLogger(__name__).warning(...)` inline | Module-level `logger` |
| `print(...)` in library code | `logger.info/debug/warning/error` |
| Raw stdout/stderr in error details | Redact or summarize |
| `__all__ = ["aider", "claude", ...]` | `pkgutil.iter_modules()` discovery |
| Hardcoded editor CLI/paths | Pluggable host adapter |
| Loader function called from many sites re-does full work every call | Cache/short-circuit inside the loader on unchanged inputs, not fewer call sites |
| Hand-rolled `_loaded`/`_ensure_loaded()` guard per registry | Shared registry utility's built-in lazy-loader |
