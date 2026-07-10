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
- **Runtime orchestration** (`runtime/harness`, `runtime/rig`, `runtime/update`, `runtime/build`) — bootstrap, lifecycle transitions, durable state. Acts as a quasi-composition root: calling foundation capabilities while bootstrapping is expected and normal. After startup, runtime should have limited need to call foundation capabilities directly — prefer events and contribution registries. This is guidance, not a hard rule; the bootstrap boundary is inherently fuzzy.

**Rules:**
- Foundation must never import runtime orchestration or components. It may import the runtime environment namespace (`runtime/system`) freely — that is the sanctioned "capability reads environment" seam.
- Environment modules (`runtime/system`) hold read-only facts only: no orchestration logic, no imports from foundation, components, or the rest of runtime.
- Runtime must never import a specific optional component. Use events or contribution registries.

  _Rationale: every real and planned use of the registered-callback pattern (`get_capability`/`register_capability`) was found to be a misapplication — either a fire-and-forget reaction better served by the event bus, logic needing no indirection at all, or composition-root code exempt from import rules that could check the component registry and import directly._

- Tests are exempt from production import constraints. Test code may import across layers, private helpers, optional components, or composition-root modules as needed to validate behavior, boundaries, fixtures, and migration safety.
- **Domain-neutral naming:** foundation module names, function names, event-type strings, and contribution-registry keys must be domain-neutral. A name referencing one specific component's vocabulary is a layering violation even when it produces zero forbidden imports.
- Composition roots are exempt from import-direction rules by definition.

## 2. Config Over Code

Extensibility must never require editing Python source.

**Rules:**
- Lists of entities (components, providers, tools, states, policies, capabilities) must be declared in YAML/JSON — never hardcoded in Python.
- `if/elif` chains that branch on entity names (component ID, provider name, action tag, file path) are prohibited. Use a registry of `(key, handler)` pairs or a config-driven lookup table.
- Adding a new capability = dropping a config file or contributing to a registry. No Python edits.

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
- **YAML registration is mandatory:** every error code used in source must have an entry in the owning component's `error-resolutions.yaml` (located at `config/components/<component>/error-resolutions.yaml`). A code raised without a YAML registration is a defect — `get_error_resolution(code)` returns the raw code string, producing unhelpful diagnostics. Do not introduce new codes without first adding them to the YAML file.
- Error ownership is split intentionally:
  - `code` is canonical identity and must be stable.
  - `message` is the concise operator-facing statement raised by code and returned in the error envelope. The inline `message=` at the raise site is acceptable as the operator-facing diagnostic; it need not match the YAML resolution text verbatim (they serve different audiences).
  - `resolution` is optional agent/operator guidance and belongs exclusively in config (`error-resolutions.yaml`). It should describe remediation steps, configuration checks, or further action — not repeat the error message.
  - `details` carries contextual diagnostics only; never use it as the primary message channel.
- **Error file ownership:** each component owns its own `error-resolutions.yaml`. The owning component is determined by the component part of the error code (e.g., AGW codes belong in the agents component's YAML, PLN codes in planning's). If a component does not yet have an error-resolutions.yaml, create one before adding codes.
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
- **Move/rename/delete verification** — when a migration moves, renames, or deletes a module, an `import`-shaped grep over `src/` is not sufficient proof it landed. The old dotted path also hides in **string-literal references** that no import scan catches — `monkeypatch.setattr("old.path...")`, `mock.patch("old.path...")`, `importlib.import_module`, patch decorators, and dotted paths in config/YAML. Grep the **whole repo including `tests/`** for the old path as a bare string, and treat only a green **full** test suite (`python -m pytest tests/unit`) — not the grep — as proof. A partial-suite run plus a `src`-only import grep is what lets a completed migration ship tests that fail with `ModuleNotFoundError` on the deleted module.

## 11. Lazy Initialization

**Principle:** Lazy loading is an implementation detail that must be invisible to callers. A consumer requests a value or capability and receives it; whether that value was pre-populated or materialized on demand is not its concern.

**Rules:**
- Prefer lazy, on-first-access loading over eager centralized bootstrap for config-driven registries, heavy dependencies, and shared state.
- **Transparency is mandatory.** The public API surface must not expose loader functions, priming methods, or load-state queries. A caller accesses the registry, property, or capability directly — laziness is handled internally.
- The lazy-load guard lives inside the accessor, not at every call site. A property getter, module-level function, or descriptor performs the on-demand population and returns the ready value. Callers never invoke a separate "ensure loaded" step.
- The internal loader must be **idempotent and cheap** on repeated invocation: re-entry is a cached no-op. If accumulation makes it expensive, fix the cost inside the guard (short-circuit on completion flag) — do not push awareness of the load state outward to callers.
- When building a registry that needs on-first-access population, prefer composing the shared registry utility's built-in lazy-loader support over hand-rolling a module-level `_loaded`/`_ensure_loaded()` guard.

## 12. Anti-Pattern Quick Reference

| Anti-pattern | Fix |
|---|---|
| Hardcoded list of entities | Config-driven or registry |
| `if x == "a": ... elif x == "b":` on entity names | `(key, handler)` registry |
| `foundation/` imports `components/` or runtime orchestration (anything outside `runtime/system`) | Invert via capability registry/events, or move the fact into `runtime/system` |
| Orchestration logic or upward imports inside `runtime/system` | Environment modules hold read-only facts only |
| `runtime/` imports optional component internals | Events, contribution registry |
| Manual `FastMCP(...)` construction | `mcp_server(__name__)` |
| `raise ValueError("...")` at public boundary | `AudiaGenticError(code=..., ...)` |
| `except Exception: pass` | Log `exc_info=True`, wrap, or safe default |
| `logging.getLogger(__name__).warning(...)` inline | Module-level `logger` |
| `print(...)` in library code | `logger.info/debug/warning/error` |
| Raw stdout/stderr in error details | Redact or summarize |
| `__all__ = ["aider", "claude", ...]` | `pkgutil.iter_modules()` discovery |
| Hardcoded editor CLI/paths | Pluggable host adapter |
| Call site must invoke a loader or check load state before using a value | Hide laziness inside the accessor; caller gets the value directly |
| Internal loader re-does full work on every call | Cache/short-circuit inside the guard (idempotent no-op after first completion) |
| Hand-rolled `_loaded`/`_ensure_loaded()` guard per registry | Shared registry utility's built-in lazy-loader |
| Single-slot registered-callback/capability lookup for a direct import | Convert to an event; or in composition-root, check component registry and import directly |
| Component-domain vocabulary in foundation module/event/registry-key name | Rename to domain-neutral concept, or move logic into owning component |
| Error code raised without error-resolutions.yaml entry | Add the code to the owning component's YAML before using it |
