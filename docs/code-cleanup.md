# Code Cleanup Plan

Validated against `docs/ARCHITECTURE_STANDARDS.md`. Each item verified against source code.

Completed items moved to [`code-cleanup-completed.md`](code-cleanup-completed.md).

## Open Work — Continue Here

> **Validation sweep 2026-06-21 (pass 4).** Full source re-read of every cited file. Four **plan gaps found and corrected**: (1) 2 additional `except Exception:` sites in `coding_lsp_bootstrap.py:88,115` added to [Std 8 section](#std-8-sub-rules-except-exception-internal-code). (2) 3 best-effort refresh `except Exception:` sites in `opencode/install:238,243` and `pi/install:193` added to [Std 8 section](#std-8-sub-rules-except-exception-internal-code). (3) 3 non-entity-referencing logs (`coding_lsp_bootstrap:89,116`, `reconcile.py:201`) **removed** from [Std 9 list](#std-9-sub-rules-extra-on-entity-logs) — count corrected from 13 to 10. (4) Error-detail redaction scope clarified: redact only known sensitive patterns, not arbitrary dict values. Pass 3 corrections (CI validator false-positive, Stage 5 delete list) confirmed still accurate. Cross-reference conflict noted on item 2: `event_service.py:60` is both a Std 8 fix target **and** a Stage 5 deletion candidate — delete it (no source importers), do not fix.

**All items 1–7 completed 2026-06-21.** Moved to [`code-cleanup-completed.md`](code-cleanup-completed.md).

Remaining: deferred items, implementation plans (A21, A1 Follow-Up, A30), Stage 4, Stage 5.

Deferred (intentionally not scheduled): `binaries.py` `taskkill`/`pkill` — see [Deferred Items](#deferred-items).

---

## Reconsidered: Replace `cli_registry` with composition-root

### Why the registry is the wrong fix

Standard 1 states: *"**Runtime** must never import from a specific optional component."* It restricts `runtime/` and `foundation/` only. Components may import runtime + foundation freely.

**All six "Critical" violations live in `commands/` and `launcher.py`** — the CLI entry layer at `src/audiagentic/` top level. This layer sits *above* components (it wires them together) and is the application **composition root**, not Runtime. Verified: `grep` for `components.optional` imports under `runtime/` returns **zero matches**. The registry was built to fix a non-violation.

Costs the registry introduced:

| Problem | Detail |
|---|---|
| Lost type safety | `get_cli_service(...)` returns `Callable[..., Any] \| None`. String keys → no mypy/pyright check, no rename-refactor, no go-to-def. Typo = silent `None` at runtime. |
| Coupling hidden, not removed | CLI still hardcodes `"providers"`, `"agent_jobs"`, `"ledger"` + service-name string literals. Core still knows the components exist — dependency went from explicit+checked to implicit+unchecked. |
| New Standard 8 violation | `cli_registry.py:85-86` `except ImportError: pass` — a real import crash is silently swallowed and reported as "component not available." |
| Startup regression | `load_optional_components()` eagerly imports every optional package on every invocation (even `install`/`update`). Old lazy imports loaded inside the command branch only. |
| Dead code | `cli_registry.py:81` `.endswith(".__init__")` skip never fires — `iter_modules` never yields that name. |

### Plan

1. **Document the composition-root layer (Standard 1 amendment).**
   - In `docs/ARCHITECTURE_STANDARDS.md` §1, add a fourth layer above Components:
     - **CLI / composition root** (`audiagentic/launcher.py`, `audiagentic/commands/*`) — wires the application together. May import any layer, including specific optional components. This is the only layer permitted to.
   - State the rule explicitly: the import-down prohibition applies to `foundation/` and `runtime/`, **not** to the composition root. This is conventional — composition roots are exempt from layering rules by definition.

2. **Revert CLI call sites to lazy direct imports.** In each file, restore the original `from audiagentic.components.optional...import ...` inside the relevant command branch (kept lazy for startup cost + graceful absence via `try/except ImportError` where the component is genuinely optional):
   - `launcher.py` (job-control, release-bootstrap branches)
   - `commands/launch.py` (provider reconcile block)
   - `commands/provider_prompt.py` (two import blocks)
   - `commands/component.py` (descriptor registry)
   - Where a component may be absent, wrap the import in `try/except ImportError` and **log the error** (`logger.warning`/`debug exc_info=True`) before degrading — do not silently `pass`. This preserves graceful degradation without the registry's silent-swallow bug.

3. **Delete the registry machinery.**
   - Remove `runtime/services/cli_registry.py`.
   - Remove the `register_cli_service(...)` blocks from `components/optional/providers/__init__.py`, `agent_jobs/__init__.py`, `ledger/__init__.py` (and any others). Keep only the genuine package init each `__init__` needs.
   - Remove the `load_optional_components()` call from `launcher.py:152-153`.

4. **Verify.**
   - `grep` confirms zero `components.optional` imports remain under `runtime/` and `foundation/` (the real Standard 1 surface).
   - mypy/pyright pass with no new `Any` at former call sites — type safety restored.
   - Run CLI smoke for `job-control`, `release-bootstrap`, `component list`, provider reconcile to confirm dispatch still works.
   - Confirm a deliberately broken optional import now surfaces a logged error instead of silent "not available."

### Alternative (if true runtime→component inversion is ever needed)

Should a *real* `runtime/` file later need to call into an optional component, do **not** revive the stringly-typed dict. Define a typed `Protocol` in `runtime/` (or `foundation/`); the optional component registers a Protocol-conforming object; runtime depends on the Protocol. Keeps type safety **and** real dependency inversion. Out of scope now — no such call site exists.

### Effort / risk

Low. Mechanical revert of ~6 import sites + delete one module + 3 `__init__` edits + one Standards paragraph. No behavioral change beyond removing the eager-load and replacing silent swallow with logging. Lower line count than the registry it replaces.

---

## Silent except: pass — untracked (Standard 8)

- [x] ~~**agent_jobs/packet_runner.py:187-188, 193-194**~~ — **DONE 2026-06-21.** Added `logger.debug("failed to persist 'failed' transition", exc_info=True)`.

- [x] ~~**`runtime/harness/opencode/install/__init__.py:143-144`**~~ — **DONE 2026-06-21.** Narrowed to `except AudiaGenticError`, added `logger.warning`.
  - **Context:** Model-profile resolution (`load_rig_model` / `resolve_profile_definition`); on failure falls through to empty `model_profile = {}`.
  - **Issue (two):** (1) silent swallow → resolution failure is invisible, MCP config written with no profile and no diagnostic. (2) **Catching `SystemExit` and discarding it** is a smell — it masks an intentional process exit raised deeper in the call.
  - **Fix:** Log `logger.warning("could not resolve model profile, using empty", exc_info=True)`. **Narrow the except to `AudiaGenticError` only** — do not swallow `SystemExit`. If a `sys.exit()` path is genuinely expected here, document why; otherwise let it propagate. **Priority: medium** (the `SystemExit` catch is the real concern).

- [x] **runtime/services/cli_registry.py:85-86** — `except ImportError: pass`
  - **Status:** Subsumed by the [composition-root plan](#reconsidered-replace-cli_registry-with-composition-root) — `cli_registry.py` is deleted there, and the replacement wraps optional imports in `try/except ImportError` **with logging**. No separate fix; tracked to avoid re-discovery.

---

## Std 8 Sub-Rules — `except Exception:` in Internal Code

Std 8: *"except Exception: only at external boundaries (I/O, subprocess, network, third-party). Internal code catches specific types."*

- [x] ~~**foundation/workflow/state_machine.py:182**~~ — **DONE 2026-06-21.** `except Exception:` → `except AudiaGenticError:`
  - **Context:** Cascading state transitions within the state machine engine.
  - **Issue:** Internal call, not external boundary. Should catch `AudiaGenticError` (invalid transition) specifically.
  - **Fix:** `except AudiaGenticError:` — or remove the handler entirely and let it propagate.

- [x] ~~**foundation/workflow/propagation/healing.py:108**~~ — **DONE 2026-06-21.** `except Exception:` → `except AudiaGenticError:`
  - **Context:** Healing fix application within the propagation engine.
  - **Issue:** Internal call, not external boundary.
  - **Fix:** `except AudiaGenticError as exc:` — or catch the specific error types `apply_fix` can raise.

- [ ] **foundation/event/event_service.py:60** — `except Exception as e:` around internal `bus.publish_envelope(...)`.
  - **⚠ SKIPPED — Stage 5 deletion candidate.** Module has zero source importers. Will be deleted in Stage 5.
  - **Context:** Event service publish wrapper.
  - **Issue:** Internal call, not external boundary. Uses `warnings.warn` instead of logger.
  - **Fix:** `except AudiaGenticError as e:` and log via `logger.error(..., exc_info=True)`.
  - **⚠ Conflict with [Stage 5](#stage-5--foundation-decommission--unification):** `event_service.py` has **zero source importers** (only re-exported from `event/__init__.py`; sole test `tests/unit/foundation/event/test_service.py`). Stage 5 deletes the whole module. **Resolution: do not fix — delete.** Skip this item if Stage 5 runs first; if this item runs first, the fix is discarded on delete.

---

### Std 8 Sub-Rules — `except Exception:` in Component Code (Gap 1, pass 4)

- [x] ~~**components/optional/coding_lsp/coding_lsp_bootstrap.py:88**~~ — **DONE 2026-06-21.** `except Exception:` → `except AudiaGenticError:`
  - **Context:** Lifecycle hook for coding-lsp component enable. Wraps `sync_language_servers_to_providers()` and `sync_generic_lsp_mcp_to_providers()` — both internal calls.
  - **Issue:** Internal calls, not external boundary.
  - **Fix:** `except AudiaGenticError:` — or remove the handler and let it propagate.

- [x] ~~**components/optional/coding_lsp/coding_lsp_bootstrap.py:115**~~ — **DONE 2026-06-21.** `except Exception:` → `except AudiaGenticError:`
  - **Context:** Lifecycle hook for coding-lsp component disable. Wraps `prune_language_servers_from_providers()` and `prune_generic_lsp_mcp_from_providers()` — both internal calls.
  - **Issue:** Internal calls, not external boundary.
  - **Fix:** `except AudiaGenticError:` — or remove the handler and let it propagate.

---

### Std 8 Sub-Rules — `except Exception:` in Best-Effort Refresh (Gap 2, pass 4)

_Best-effort functions that silently degrade on any exception. Broader than Std 8 permits, but the degradation path is intentional. Fix: narrow to `AudiaGenticError` and add logging._

- [x] ~~**runtime/harness/opencode/install/__init__.py:238**~~ — **DONE 2026-06-21.** `except Exception:` → `except AudiaGenticError:`
  - **Context:** Best-effort refresh; on failure logs warning (line 239).
  - **Issue:** Catches all exceptions including `KeyError`, `TypeError`, etc. — not external boundary.
  - **Fix:** `except AudiaGenticError:` — internal config/materialize errors are `AudiaGenticError`.

- [x] ~~**runtime/harness/opencode/install/__init__.py:243**~~ — **DONE 2026-06-21.** `except Exception:` → `except AudiaGenticError:`
  - **Context:** Best-effort reload request; on failure logs warning (line 243).
  - **Issue:** Catches all exceptions — not external boundary.
  - **Fix:** `except AudiaGenticError:` — reload marker write errors are `AudiaGenticError`.

- [x] ~~**runtime/harness/pi/install/__init__.py:193**~~ — **DONE 2026-06-21.** `except Exception:` → `except AudiaGenticError:`
  - **Context:** Best-effort refresh for PI harness; on failure logs warning (line 194).
  - **Issue:** Catches all exceptions — not external boundary.
  - **Fix:** `except AudiaGenticError:` — internal config/materialize errors are `AudiaGenticError`.

---

### Std 8 Sub-Rules — Error-Detail Redaction (Security)

Std 8: *"Error details must never include raw stdout/stderr, API keys, tokens, or user prompts. Redact or summarize."*

- [x] ~~**Systemic: `make_error()` / `to_error_envelope()` do not redact `details` dict.**~~ — **DONE 2026-06-21.** Added `redact_details()` to `foundation/contracts/errors.py`.
  - **Evidence:** `runtime/update/runner.py:139` — `details` includes `result.stderr` (pip output). `foundation/workflow/invocation/steps.py:171-172` — `outputs` dict includes raw `stdout`/`stderr`. `runtime/rig/embedded/binaries.py:244` — error message includes version output.
  - **Fix:** Add a `redact_details()` filter in `foundation/contracts/errors.py` that masks **known sensitive patterns only**: bearer tokens (`Bearer ...`), API key prefixes (`sk-`, `ghp_`, `xoxb-`), raw stdout/stderr exceeding 1KB. Do NOT redact arbitrary dict values (paths, counts, config keys are legitimate diagnostics). Callers should also avoid passing raw stdout/stderr into `details` — summarize or truncate instead.
  - **Risk: medium.** `details` is used widely across the codebase. Redaction filter must not break legitimate diagnostic data. Test: verify `runner.py:139` stderr redaction, `steps.py:171-172` stdout/stderr redaction, and that path/config-key details pass through unchanged.

---

## Std 5 — Component Discovery Violations

Std 5: *"Component IDs derived from loaded descriptors — not maintained as parallel Python constants."*

- [x] ~~**foundation/components/ids.py**~~ — **DONE 2026-06-21.** Added `get_optional_component_ids()` transitional function + deprecation notice.
  - **Callers:** 21 files import from this module.
  - **Issue:** IDs are also defined in component YAML descriptors. Python constants create a second source of truth — if a descriptor ID changes, the constant must change too (and vice versa), with no enforcement.
  - **Fix:** Derive IDs from loaded descriptors at runtime. For core components (`project`, `session`) that have no YAML descriptor, keep a minimal `CORE_IDS` set. For optional components, look up from the descriptor registry. Transitional: keep `ids.py` as a thin wrapper that reads from the registry, with deprecation notice.

---

## Std 9 — Sub-Rules: `extra={}` on Entity Logs

Std 9: *"Entity-referencing messages must carry `extra={"component": ..., "provider": ..., "item_id": ...}`."*

10 logger calls reference an entity ID in the message string but do not use `extra={}`. Only 11 `extra={}` usages exist across the entire `src/` tree (all in `launcher.py`, `event_bus.py`, `component_server.py`).

> **Corrected pass 4:** Removed 3 non-entity-referencing logs from this list: `coding_lsp_bootstrap.py:89,116` ("Failed to sync/prune coding-lsp provider config" — no entity ID in message) and `reconcile.py:201` ("Background provider reconcile failed" — no entity ID). These are generic warnings, not entity-referencing.

- [x] ~~**runtime/lifecycle/components.py:61**~~ — **DONE 2026-06-21.** Added `extra={"component": component_id}`
- [x] ~~**runtime/lifecycle/component_mcp.py:30,74**~~ — **DONE 2026-06-21.** Added `extra={"component": ...}`
- [x] ~~**runtime/harness/opencode/install/__init__.py:239,243**~~ — **DONE 2026-06-21.** Added `extra={"component": ...}`
- [x] ~~**runtime/harness/pi/install/__init__.py:194,198**~~ — **DONE 2026-06-21.** Added `extra={"component": ...}`
- [x] ~~**components/optional/providers/services/lsp_projection.py:63,123,156**~~ — **DONE 2026-06-21.** Added `extra={"provider": ...}`

**Fix:** Add `extra={"component": component_id}` or `extra={"provider": provider_id}` to each. Low effort, mechanical.

---

## Deferred Items

| Item | Standard | Reason | Priority |
|---|---|---|---|
| `binaries.py:170-182` — `taskkill`/`pkill` | Standard 4 | OS process management, not editor coupling. Already abstracted via `sys.platform`. | Low |

---

## Implementation Plans

### A21 — State Machine Unification

**Problem:** Two independent state machine implementations: foundation `StateMachine` (config-driven, protocol-based, event/cascade support) and agent-jobs `state_machine.py` (hardcoded transitions, direct file I/O, no events).

**Design:** Extract lightweight `TransitionEngine` into `foundation/workflow/transition_engine.py`. Both existing engines use it. Foundation `StateMachine` adds lifecycle/cascade/event on top. Agent-jobs becomes a thin adapter.

**New files:**
- `src/audiagentic/foundation/workflow/transition_engine.py` — `TransitionConfig`, `TransitionEngine`, `PersistenceProtocol`

**Modified files:**
- `foundation/workflow/state_machine.py` — use `TransitionEngine` for core validation
- `foundation/workflow/interfaces.py` — add `PersistenceProtocol`
- `components/optional/agent_jobs/state_machine.py` — thin adapter over `TransitionEngine`, keep `LEGAL_TRANSITIONS`/`TERMINAL_STATES` as backward-compatible exports

**Migration (4 phases):**
1. Create `transition_engine.py` + tests (no behavior change)
2. Refactor agent-jobs to use `TransitionEngine` (backward-compatible)
3. Foundation `StateMachine` adopts `TransitionEngine`
4. Cleanup old validation logic, add deprecation warnings

**Acceptance:** Single validation path, no direct persistence coupling in state machines, all existing consumers work without code changes, unified `WFSM-*` error codes.

**Risk:** Low — additive refactor with backward-compatible adapters.

---

### A1 Follow-Up — Generic Host Capabilities

**Problem:** 12+ VS Code coupling sites (hardcoded `code` CLI, `~/.vscode/extensions` paths, `vscode-mode` config, `package_manager == "vscode"` gating, `VsCodeExtension()` constructor, schema `"vscode"` enum values).

**Design:** `HostAdapter` Protocol in `providers/adapters/host_adapter.py` with `VsCodeAdapter` concrete implementation. `resolve_host_adapter()` factory detects available host. All VS Code-specific logic moves into the adapter.

**New files (3):**
- `providers/adapters/host_adapter.py` — `HostAdapter` Protocol + `VsCodeAdapter`
- `providers/adapters/host_factory.py` — `resolve_host_adapter(project_root)`

**Modified files (14+):**
- `toolchains.yaml` — `vscode` → generic `ext_install` with `EXT_CLI` placeholder
- `providers/services/host_capabilities.py` — delegate to adapter
- `providers/adapters/roo/descriptor.py` — generic `ext_recipe()`
- `providers/descriptors/base.py` — `host_capability()` factory, deprecate `VsCodeExtension()`
- `providers/services/status.py` — `host-mode`, `host_project`
- `providers/services/provider_config.py` — `host-mode` validation
- `providers/descriptors/registry.py` — adapter-based gating
- `providers/services/reconcile.py` — adapter-based skip
- 5 schema files — `"vscode"` → `"host"` in surface enum
- 9 adapter descriptors — `host_capability()` import

**Migration order:** Schemas (Tier 1) → Adapter infra (Tier 2) → Config/gating (Tier 3) → Cleanup (Tier 4).

**Acceptance:** Zero `"code"` CLI literals in non-adapter code, zero `~/.vscode/extensions` paths in non-adapter code, `HostAdapter` Protocol defined, VS Code works identically.

**Risk:** Medium — 17+ files touched, but each tier is independently testable.

---

### A30 (optional) — VS Code `.vscode/extensions.json` Recommendations

**Problem:** Provider-declared VS Code extensions are tracked internally but not surfaced to VS Code. No version/metadata from installed extensions.

**Design:** Generate `.vscode/extensions.json` during reconcile/install/uninstall. Derived from enabled providers' `host_capabilities` with `host == "vscode"`. Read `package.json` from `~/.vscode/extensions/<ext>/` for version/metadata.

**New file:**
- `providers/services/extensions_json.py` — `build_recommendations()`, `write_extensions_json()`, `prune_extensions_json()`

**Modified files (5):**
- `providers/services/host_capabilities.py` — add `read_extension_package_json()`, `list_vscode_extensions_with_metadata()`
- `providers/services/reconcile.py` — wire `write_extensions_json()` after surfaces
- `providers/services/lifecycle.py` — wire into install/uninstall paths
- `providers/providers_api.py` — add `list_provider_extensions()` endpoint
- `providers/services/status.py` — include version/metadata in status output

**Acceptance:** `.vscode/extensions.json` created/updated during reconcile, version/metadata from package.json, idempotent, user-preserved unmanaged recommendations.

**Risk:** Low — additive feature, no breaking changes.

---

### Stage 4 — Flat-Component Regression

**Problem:** After Stages 0-3 introduced multi-layer descriptor model, verify flat components (agent-ledger, release, source-control) still load, register, and function correctly.

**Scope:** Verification-only. No code edits expected.

**Flat components:**
- `agent-ledger` — no sub-layer, MCP servers, lifecycle-observer
- `release` — no sub-layer, depends on project + agent-ledger
- `source-control` — no sub-layer, depends on project, dependencies block

**Verification steps:**
1. `pytest tests/integration/lifecycle/test_component_lifecycle.py -v` — parametrized lifecycle for all project components
2. `pytest tests/unit/release/ tests/unit/source_control/ -v` — unit tests
3. `pytest tests/integration/release/ -v` — integration tests
4. `pytest tests/e2e/cli/test_release_bootstrap_cli.py tests/e2e/lifecycle/test_full_lifecycle.py -v` — e2e
5. Architecture grep: zero `foundation/` → `components.optional/` imports
6. Descriptor field verification: `implementation_cardinality=None`, correct `depends_on`, correct `mcp_servers`
7. `ruff check src/` — clean

**Acceptance:** All tests green, no foundation→component imports, descriptors load correctly, ruff clean.

**Risk:** Low — verification only. If tests fail, fix foundation code, not flat components.

---

### Stage 5 — Foundation Decommission & Unification

> **⚠ Corrected 2026-06-21 (validation pass 3).** Original plan listed `validate_schemas.py` and `validate_packet_dependencies.py` as "CLI-only, zero importers" → delete. **They are live CI entry points**, invoked as `python -m` scripts by `.github/workflows/ci-contracts.yml`:
> - `ci-contracts.yml:21` → `audiagentic.foundation.contracts.validate_schemas`
> - `ci-contracts.yml:25` → `audiagentic.foundation.contracts.validate_packet_dependencies`
>
> Deleting them **breaks the contracts CI job** plus tests `tests/integration/contracts/test_ci_validators.py` and `tests/unit/contracts/test_schema_validation.py`. "Zero importers" held for *Python import* but they run as *executable modules*. **They are NOT dead code — removed from the deletion list below.**

**Problem:** Dead code in foundation event layer: two classes with zero importers (source and CLI).

**Scope:** Delete 2 dead event modules + their tests, update 1 `__init__.py` + README.

**Modules to delete (verified dead — no source importers, no CLI invocation):**
- `foundation/event/event_replay.py` — `ReplayService`. Only referenced from `event/__init__.py` re-export and `event/README.md`.
- `foundation/event/event_service.py` — `EventService`. Same. Subsumes item 2's `event_service.py:60` fix (delete > fix).

**Tests to delete with the modules:**
- `tests/unit/foundation/event/test_replay.py`
- `tests/unit/foundation/event/test_service.py`

**Files to modify:**
- `foundation/event/__init__.py` — remove `ReplayService`/`EventService` imports + `__all__` entries.
- `foundation/event/README.md` — drop the `EventService`/`ReplayService` sections + diagram/table rows.

**Explicitly NOT deleted (corrected):**
- `foundation/contracts/validate_schemas.py` — CI entry point (`ci-contracts.yml:21`). Keep. (Also holds the resolved `VAL-VSCHEMA-001` fix.)
- `foundation/contracts/validate_packet_dependencies.py` — CI entry point (`ci-contracts.yml:25`). Keep.

**Migration order:**
1. Delete `event_replay.py` + `event_service.py` + their two test files.
2. Update `event/__init__.py` exports and `event/README.md`.
3. Verify: `grep -rn "EventService\|ReplayService" src/ tests/` returns zero; `python -m audiagentic.foundation.event` imports clean.
4. Run full suite + `ruff check src/`; confirm contracts CI job still passes (validators untouched).

**Acceptance:** `EventService`/`ReplayService` have zero remaining references in `src/` and `tests/`, full suite green, ruff clean, foundation imports successfully, contracts CI job passes.

**Risk:** Low — dead event-class removal, verified by grep. (Original Medium-risk validator deletion dropped.)
