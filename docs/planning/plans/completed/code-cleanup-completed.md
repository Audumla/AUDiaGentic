# Code Cleanup — Completed

Resolved items moved from `code-cleanup.md`. Chronological order.

---

## Critical — Layer Boundaries (Standard 1)

Direct imports from `components.optional.*` in core code. Fix: `cli_registry` with `pkgutil` discovery.

- [x] **launcher.py:172-175** — `from audiagentic.components.optional.agent_jobs.control import ...`
- [x] **launcher.py:209** — `from audiagentic.components.optional.ledger import ...`
- [x] **commands/launch.py:49-58** — `from audiagentic.components.optional.providers.services.provider_config import ...` and `...lifecycle import ...`
- [x] **commands/provider_prompt.py:30-33** — `from audiagentic.components.optional.providers.services.lifecycle import ...`
- [x] **commands/provider_prompt.py:58-62** — same module, second import block
- [x] **commands/component.py:49-54** — `from audiagentic.components.optional.providers.descriptors.registry import ...`

**Fix applied:** `runtime/services/cli_registry.py` — `pkgutil`-driven discovery of optional components. Each optional component's `__init__.py` registers its CLI services. CLI dispatches through `get_cli_service()`. No hardcoded package list.

> **⚠ Under reconsideration — see `code-cleanup.md` [Reconsidered: composition-root approach](code-cleanup.md#reconsidered-replace-cli_registry-with-composition-root).** The registry satisfies Standard 1 literally but introduces a net regression.

---

## Critical — Error Handling (Standard 8)

Raw `ValueError` at public foundation boundary. Fix: `AudiaGenticError` with canonical code.

- [x] **foundation/contracts/validate_schemas.py:30** — `VAL-VSCHEMA-001`

---

## Warning — Error Handling (Standard 8)

Raw `ValueError` at public boundary. Fix: `AudiaGenticError` with canonical code.

- [x] **foundation/contracts/validate_ids.py:53** — `VAL-VIDS-001`
- [x] **components/optional/providers/skill_surfaces.py:67** — `VAL-PROV-SKILL-001`
- [x] **components/optional/providers/skill_surfaces.py:119** — `VAL-PROV-SKILL-002`
- [x] **components/optional/providers/skill_surfaces.py:127** — `VAL-PROV-SKILL-003`
- [x] **components/optional/providers/skill_surfaces.py:130** — `VAL-PROV-SKILL-004`
- [x] **components/optional/providers/skill_surfaces.py:134** — `VAL-PROV-SKILL-005`

---

## Warning — Error Handling (Standard 8)

Silent `except ... pass` without logging. Fix: log `exc_info=True` or safe default.

- [x] **commands/launch.py:106-107** — `except (OSError, ValueError): pass` (signal handler registration)

---

## Warning — Logging (Standard 9)

Missing module-level logger in library code. Fix: add `logger = logging.getLogger(__name__)`.

- [x] **runtime/harness/pi/runner/agent_run.py** — no module-level logger
- [x] **runtime/harness/opencode/runner/__init__.py** — no module-level logger

---

## Resolved — Error Handling (Standard 8) — 2026-06-21

#### [x] paths.py — RuntimeError → AudiaGenticError

- **File:** `src/audiagentic/paths.py:61-64`
- **Fix:** `RuntimeError` → `AudiaGenticError(code="CFG-PATHS-001", kind="paths", ...)`
- **Details:** Added `details={"anchor": str(anchor)}`

#### [x] providers/tags/loader.py — ValueError → AudiaGenticError

- **File:** `src/audiagentic/components/optional/providers/tags/loader.py:124`
- **Fix:** `ValueError` → `AudiaGenticError(code="VAL-PTAG-004", kind="providers", ...)`

#### [x] providers/protocols/streaming/provider_streaming.py — ValueError (×2) → AudiaGenticError

- **File:** `src/audiagentic/components/optional/providers/protocols/streaming/provider_streaming.py:103,116`
- **Fix:** `VAL-PROV-STREAM-001` (sink-error-policy), `VAL-PROV-STREAM-002` (termination-policy)

#### [x] providers/protocols/streaming/sinks.py — ValueError → AudiaGenticError

- **File:** `src/audiagentic/components/optional/providers/protocols/streaming/sinks.py:219`
- **Fix:** `AudiaGenticError(code="VAL-PROV-SINK-001", kind="providers-streaming", ...)`

#### [x] providers/adapters/codex/mcp_format.py — ValueError (×6) → AudiaGenticError

- **File:** `src/audiagentic/components/optional/providers/adapters/codex/mcp_format.py`
- **Fix:** `VAL-PROV-CODEX-MCP-001` (unsupported type), `VAL-PROV-CODEX-MCP-002` (invalid TOML), `VAL-PROV-CODEX-MCP-003` (read error), `VAL-PROV-CODEX-MCP-004` (invalid config shape), `VAL-PROV-CODEX-MCP-005` (invalid entry shape)

#### [x] providers/adapters/codex/language_servers.py — ValueError → AudiaGenticError

- **File:** `src/audiagentic/components/optional/providers/adapters/codex/language_servers.py:39`
- **Fix:** `AudiaGenticError(code="VAL-PROV-CODEX-LSP-001", kind="providers-codex", ...)`

#### [x] providers/adapters/goose/mcp_format.py — ValueError → AudiaGenticError

- **File:** `src/audiagentic/components/optional/providers/adapters/goose/mcp_format.py:43`
- **Fix:** `AudiaGenticError(code="VAL-PROV-GOOSE-MCP-001", kind="providers-goose", ...)`

---

## Resolved — Silent except: pass (Standard 8)

#### [x] foundation/logging/formatters.py — Silent pass → logger.debug

- **File:** `src/audiagentic/foundation/logging/formatters.py:110-111`
- **Fix:** `pass` → `logging.getLogger(__name__).debug("failed to close stream during rollover", exc_info=True)`

#### [x] foundation/event/event_bus.py — Non-issue

- **Assessment:** `pass` in `@abstractmethod` stubs — required Python syntax. Not a violation.

---

## Resolved — Missing Module-Level Loggers (Standard 9)

#### [x] agent_jobs modules — 7 modules

- **Files:** `stages.py`, `state_machine.py`, `records.py`, `profiles.py`, `prompt_targets.py`, `prompt_syntax.py`, `prompt_aliases.py`
- **Fix:** Added `import logging` and `logger = logging.getLogger(__name__)` to each

---

## Swept and Confirmed Compliant (2026-06-21)

### Std 3 — Logic Containment

Largest file is 99 lines. Zero god objects, zero dataclass dedup needed.

### Std 7 — Virtual Assets

No path-based branching for generated files. `materialize_agent_config()` calls dedicated functions per asset type.

### Std 9 — MCP Args Never Logged

`component_server.py:127-128` enforces "Args are never logged". Compliant.

### Silent except: pass — ~30 sites reviewed

All Standard 8-compliant: resource teardown (`process.py`, `id_gen.py`, `lsp_bridge.py`, `rig/embedded/launch.py` `os.kill`/`close`/`unlink` on `OSError`), logging-handler close on shutdown (`logging/config.py`, `logging/audit.py`), and JSON-parse fallbacks returning a safe default (provider adapters, `mcp_format`/`json_format` merge-existing-config). `FastMCP(...)` construction: only the sanctioned factory in `foundation/mcp/component_server.py`. No stray `print()` in `runtime/`.

---

## Not Included (Validated as Non-Issues)

| Item | Reason |
|---|---|
| `validate_schemas.py:53` | No `ValueError` at this line — agent error |
| `pi/install/__init__.py:100` | Directory structure for binary distribution, not platform coupling |
| `binaries.py:216-221` | `_PLATFORM_PATTERNS` dict is config-driven (Standard 2 compliant) |
| `update/runner.py:50-52,125` | Windows frozen exe auto-update is intentional design |
| `binaries.py:173-182` | OS process management, not editor coupling — Standard 4 scope is editors |
| `event_bus.py:72,80,84` | `pass` in `@abstractmethod` stubs — required Python syntax |
| `cli_io.py:34,39,44` | Dedicated CLI output module — `print()` is intentional |
| `agent_jobs/control.py:131,204` | `print()` in docstring examples, not executed code |
| `providers/workflow/provider_cli.py:140,142,233,241` | Action dispatch (`install`/`uninstall`), not entity name branching |
| `agent_jobs/reviews.py:38-42,51` | Type dispatch (`packet`/`job`), not hardcoded entity list |
| `agent_jobs/profiles.py:11-30` | Configuration data dict, not code logic |

---

## Resolved — 2026-06-21 Session

### [x] Std 1 — Move `LanguageServerEntry` out of foundation

- **Source:** `foundation/language_servers.py` (deleted)
- **Target:** `components/optional/coding_lsp/language_servers.py` (created)
- **Importers updated:** `language_servers_sync.py:24`, `providers/descriptors/base.py:8`, `providers/services/lsp_projection.py:7`
- **Reason:** Std 1 violation — LSP-specific domain data in foundation layer

### [x] Item 1 — Error-detail redaction (Std 8 security)

- **File:** `foundation/contracts/errors.py`
- **Added:** `_REDACT_PATTERNS` (compiled regex: bearer tokens, `sk-`/`ghp_`/`xoxb-` prefixes), `_redact_value()` recursive helper, `redact_details()` public function
- **Wired into:** `make_error()`, `to_error_envelope()`, `_Error.__post_init__()`
- **Behavior:** Truncates `stdout`/`stderr` >1024 chars; redacts API key/token patterns; leaves paths/counts/config keys unchanged

### [x] Item 5 — cli_registry composition-root revert (Std 1)

- **Deleted:** `runtime/services/cli_registry.py`
- **Reverted 6 CLI call sites** to lazy direct imports with `try/except ImportError`:
  - `launcher.py` (job-control, release-bootstrap branches)
  - `commands/launch.py` (provider reconcile)
  - `commands/provider_prompt.py` (two import blocks)
  - `commands/component.py` (descriptor registry)
- **Cleaned 3 `__init__.py` files:** removed `register_cli_service()` blocks from `providers/`, `agent_jobs/`, `ledger/`
- **Amended:** `ARCHITECTURE_STANDARDS.md` §1 — added "CLI / composition root" layer above Components

### [x] Item 2 — except Exception: internal code fixes (Std 8) — 7 sites

| File | Line | Fix |
|---|---|---|
| `foundation/workflow/state_machine.py` | 182 | `except AudiaGenticError:` (cascade `self.state()` call) |
| `foundation/workflow/propagation/healing.py` | 108 | `except AudiaGenticError:` (internal `apply_fix()` call) |
| `coding_lsp/coding_lsp_bootstrap.py` | 88 | `except AudiaGenticError:` (internal `_on_enabled()` LSP sync) |
| `coding_lsp/coding_lsp_bootstrap.py` | 116 | `except AudiaGenticError:` (internal `_on_disabled()` LSP prune) |
| `opencode/install/__init__.py` | 238 | `except AudiaGenticError:` (internal config/materialize) |
| `opencode/install/__init__.py` | 243 | `except AudiaGenticError:` (internal reload request) |
| `pi/install/__init__.py` | 193, 197 | `except AudiaGenticError:` (internal config + reload) |

SKIPPED: `foundation/event/event_service.py:60` — Stage 5 will delete the entire module (zero source importers)

### [x] Item 6 — opencode/install SystemExit catch (Std 8)

- **File:** `runtime/harness/opencode/install/__init__.py:143`
- **Fix:** `except (AudiaGenticError, SystemExit): pass` → `except AudiaGenticError: logger.warning("could not resolve model profile, using empty", exc_info=True)`
- **Reason:** Do not swallow `SystemExit`; add logging for resolution failures

### [x] Item 3 — Parallel component ID constants (Std 5)

- **File:** `foundation/components/ids.py`
- **Added:** `get_optional_component_ids()` transitional function — derives optional component IDs from loaded descriptors via `all_descriptors()`. Returns empty frozenset if registry not yet populated.
- **Added:** Deprecation notice to docstring and optional ID constants section
- **Kept:** Core IDs (`COMPONENT_PROJECT`, `COMPONENT_SESSION`) and backward-compatible constants during transition

### [x] Item 4 — Entity logs missing extra={} (Std 9) — 10 sites

| File | Lines | Fix |
|---|---|---|
| `runtime/lifecycle/components.py` | 61 | `extra={"component": component_id}` |
| `runtime/lifecycle/component_mcp.py` | 30, 74 | `extra={"component": ...}` |
| `runtime/harness/opencode/install/__init__.py` | 239, 243 | `extra={"component": component_id}` |
| `runtime/harness/pi/install/__init__.py` | 194, 198 | `extra={"component": component_id}` |
| `providers/services/lsp_projection.py` | 63, 123, 156 | `extra={"provider": descriptor.provider_id}` |

### [x] Item 7 — packet_runner silent pass (Std 8)

- **File:** `components/optional/agent_jobs/packet_runner.py:187-188, 193-194`
- **Fix:** `except AudiaGenticError: pass` → `except AudiaGenticError: logger.debug("failed to persist 'failed' transition", exc_info=True)`
- **Added:** `import logging` and `logger = logging.getLogger(__name__)` module-level logger
