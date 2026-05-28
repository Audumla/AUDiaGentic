---
id: task-346
label: Implement centralized logging overhaul
state: draft
summary: >
  Replace ad-hoc per-module logging with a layered, file-configured, structured
  logging system covering diagnostic logs, AI audit logs, correlation ID
  propagation, and per-subsystem instrumentation.
---

# Description

Audit revealed the codebase has correct per-module `logging.getLogger(__name__)` usage but no central configuration, no structured output, no correlation ID injection, no file handlers, no exc_info discipline, and no AI communication audit capability. This task implements the full logging stack.

## Log-level convention

Before any implementation work, this is the binding rule for all log call sites:

| Level    | Use for                                                                        |
|----------|--------------------------------------------------------------------------------|
| DEBUG    | Data reads, intermediate state, MCP tool names + correlation ID, config values |
| INFO     | State mutations, lifecycle transitions, tool completion + duration             |
| WARNING  | Recovered failures, missing optional deps, stale markers                       |
| ERROR    | Unrecovered failures, tool crashes, config parse errors + `exc_info=True`      |
| CRITICAL | Process-exit scenarios                                                         |

**Rule:** every `except` block that logs must use `exc_info=True`. Blind re-raise after logging is fine; silent swallow requires an explicit justification comment.

## JSON log schema

All JSON log lines conform to:

```json
{
  "ts": "2026-05-27T12:00:00.000Z",
  "level": "INFO",
  "logger": "audiagentic.runtime.lifecycle.components",
  "msg": "installed component ledger",
  "correlation_id": "a1b2c3d4",
  "exc_info": null,
  "component_id": "ledger",
  "duration_ms": 123
}
```

Extra fields (`component_id`, `duration_ms`, etc.) injected by callers via `extra={}`. No custom Filter required for field injection.

## Package structure

All logging files live in a dedicated subpackage:

```text
src/audiagentic/foundation/logging/
    __init__.py          # re-exports: configure_logging, bootstrap, get_ai_audit_logger
    context.py           # correlation ID via contextvars  (was: log_context.py)
    config.py            # load_logging_config, configure_logging, reset_logging_for_test
    bootstrap.py         # bootstrap() entry-point helper
    audit.py             # AiAuditLogger, get_ai_audit_logger
```

`src/audiagentic/foundation/log_context.py` (created in a prior session) moves into this package as `context.py`. The old path becomes a shim re-exporting from the new location to avoid breaking any existing imports, then is removed once all call sites are updated in this task.

## Config file design

### Infrastructure: `runtime/config/layered.py`

The existing `load_layered_config` function already implements the layered merge pattern used by harness, rig, and other subsystems. The logging subsystem **must use it** rather than rolling its own YAML loader.

```python
# existing signature
def load_layered_config(
    *,
    pkg_default_path: Path,
    project_root: Path | None = None,
    namespace: str,
) -> dict[str, Any]:
    """Loads: pkg default → user-global → project-local (deep-merge)."""
```

Resolved paths for namespace `foundation/logging`:

- Package default: `src/audiagentic/config/provisioning/foundation/logging.yaml`
- User-global: `~/.audiagentic/config/foundation/logging.yaml`
- Project-local: `<project_root>/.audiagentic/config/foundation/logging.yaml`

### Fourth tier: machine-local override

`load_layered_config` has three tiers. A fourth tier (machine-local, gitignored) is needed. Rather than modifying the shared function, `logging/config.py` adds a thin wrapper:

```python
def _load_raw_config(project_root: Path | None) -> dict:
    try:
        cfg = load_layered_config(
            pkg_default_path=_PKG_DEFAULT,
            project_root=project_root,
            namespace="foundation/logging",
        )
    except SystemExit:
        # load_layered_config raises SystemExit on malformed YAML.
        # Logging config must never crash the process — fall back to defaults.
        print("[audiagentic] WARNING: logging config malformed, using defaults", file=sys.stderr)
        cfg = load_yaml_file(_PKG_DEFAULT)

    # Fourth tier: project-local machine override (gitignored)
    if project_root is not None:
        local_path = project_root / ".audiagentic" / "config" / "foundation" / "logging.local.yaml"
        if local_path.exists():
            try:
                local = load_yaml_file(local_path)
                cfg = _merge_logging_config(cfg, local)
            except SystemExit:
                print(f"[audiagentic] WARNING: {local_path} malformed, skipping", file=sys.stderr)

    return cfg
```

### Layered precedence (later overrides earlier)

1. Package default — `src/audiagentic/config/provisioning/foundation/logging.yaml`
2. User-global — `~/.audiagentic/config/foundation/logging.yaml`
3. Project-local — `<project_root>/.audiagentic/config/foundation/logging.yaml` (committed)
4. Machine-local — `<project_root>/.audiagentic/config/foundation/logging.local.yaml` (gitignored)
5. Env vars — CI/container escape hatch, always highest priority

### Schema

The package default YAML (`src/audiagentic/config/provisioning/foundation/logging.yaml`) ships with all keys and their defaults, matching the `ag.yaml` convention:

```yaml
# AUDiaGentic foundation logging — package defaults.
#
# Override hierarchy (deep-merge, lowest priority first):
#   1. This file              — package defaults
#   2. User-global            — ~/.audiagentic/config/foundation/logging.yaml
#   3. Project-local          — <project>/.audiagentic/config/foundation/logging.yaml
#   4. Machine-local          — <project>/.audiagentic/config/foundation/logging.local.yaml
#   5. Env vars               — highest priority, always applied last
#
# Set exclusive_local: true in the project-local file to skip the user-global tier.

logging:
  level: INFO              # DEBUG | INFO | WARNING | ERROR
  format: json             # json | dev
  dir: null                # null = stdout only; path = write diagnostic log here

  diagnostic:
    backup_count: 30       # days of daily-rotated files to keep

  ai_audit:
    enabled: false         # off by default — zero overhead when disabled
    level: full            # full | summary | metadata_only
    redact: true           # strip API keys, bearer tokens, email patterns
    backup_count: 7        # days

  loggers: {}              # per-logger level overrides — later layers win per key

  silenced:                # loggers forced to WARNING — APPENDED across layers (union)
    - mcp
    - asyncio
    - httpx
    - urllib3
```

**List merge semantics** — `_deep_merge` in `layered.py` replaces lists. The logging wrapper adds a post-merge step:

- `silenced:` — **union** across all layers. Collected and deduplicated after all merges complete.
- `loggers:` — dict-merge as normal; later-layer key wins.

### Env var overrides

Applied last, after all file tiers. Env vars always win.

| Env var                        | Overrides                         | Notes            |
|--------------------------------|-----------------------------------|------------------|
| `AUDIAGENTIC_LOG_LEVEL`        | `logging.level`                   |                  |
| `AUDIAGENTIC_LOG_FORMAT`       | `logging.format`                  | `json` or `dev`  |
| `AUDIAGENTIC_LOG_DIR`          | `logging.dir`                     |                  |
| `AUDIAGENTIC_LOG_BACKUP_COUNT` | `logging.diagnostic.backup_count` |                  |
| `AUDIAGENTIC_AI_AUDIT`         | `logging.ai_audit.enabled`        | `on` / `off`     |
| `AUDIAGENTIC_AI_AUDIT_LEVEL`   | `logging.ai_audit.level`          |                  |
| `AUDIAGENTIC_AI_AUDIT_REDACT`  | `logging.ai_audit.redact`         | `true` / `false` |

### Config discovery

`bootstrap(component_id, project_root=None)` resolves project root via:

1. Explicit `project_root` argument
2. `AUDIAGENTIC_REPO_ROOT` env var
3. CWD walk upward looking for `.audiagentic/` — **max 10 levels, 500ms wall-clock cap; result cached after first resolution**
4. Falls back to no project-level tiers (package default + user-global + env vars only)

Malformed YAML in any tier → print WARNING to stderr, skip that tier, continue with remaining tiers. Never crash on config parse error.

At DEBUG level, log which config files were found and merged.

### Example config for users

Ship `src/audiagentic/config/provisioning/foundation/logging.yaml` as the canonical example. Users who want project-level or local overrides copy relevant sections into:

- `<project>/.audiagentic/config/foundation/logging.yaml` (committed, shared)
- `<project>/.audiagentic/config/foundation/logging.local.yaml` (gitignored, local)

---

# Implementation Steps

## Step 1 — Create `foundation/logging/` package

Create `src/audiagentic/foundation/logging/__init__.py` with re-exports.

Move `foundation/log_context.py` → `foundation/logging/context.py`. Add a shim at the old path re-exporting all four functions; remove shim once all internal imports are updated (within this task).

## Step 2 — `foundation/logging/context.py`

Correlation ID via `contextvars.ContextVar`. Works across asyncio tasks and thread pools.

Functions: `new_correlation_id()`, `set_correlation_id()`, `get_correlation_id()`, `reset_correlation_id()`.

`reset_correlation_id()` accepts no arguments and resets to `None` (used by `reset_logging_for_test()` to prevent correlation ID leakage across test cases).

## Step 3 — Package default config

Create `src/audiagentic/config/provisioning/foundation/logging.yaml` with full schema and defaults (see schema section above, including the override-hierarchy comment matching the `ag.yaml` style).

Add a path constant in `foundation/logging/config.py`:

```python
from audiagentic.runtime.harness.paths import find_package_root
_PKG_ROOT = find_package_root(Path(__file__))
_PKG_DEFAULT = _PKG_ROOT / "config" / "provisioning" / "foundation" / "logging.yaml"
```

## Step 4 — `foundation/logging/config.py`

Central config loader and `logging.config.dictConfig` driver.

### Config loading

Uses `load_layered_config` from `runtime/config/layered.py` — **no custom YAML parsing**. Adds the fourth (machine-local) tier and `silenced:` union logic on top.

```python
def load_logging_config(project_root: Path | None = None) -> LoggingConfig:
    """Merge pkg default → user-global → project → local → env vars.
    
    Uses load_layered_config for the first three tiers, then applies the
    machine-local file and env var overrides. Catches SystemExit from
    malformed YAML in any tier and falls back gracefully.
    """
```

- Cache parsed result in `_loaded_config`; re-read only after `reset_logging_for_test()`
- Post-merge: collect `silenced:` lists from all tiers and union them before building `LoggingConfig`

### `configure_logging(project_root=None)`

- Idempotency guard via `_configured` flag
- Handlers:
  - `StreamHandler(sys.stderr)` always present
  - `TimedRotatingFileHandler(when="midnight", backupCount=N)` when `dir` is set — diagnostic only
  - **No size cap** — see Notes
- Formatters:
  - `json`: custom `CorrelationJsonFormatter` reading `get_correlation_id()`, emitting schema above
  - `dev`: `%(asctime)s %(levelname)-8s [%(name)s] %(message)s`, ANSI colour when `sys.stderr.isatty()`
- `RedactionFilter` applied to **AI audit handler only** — not diagnostic handlers (performance; diagnostic logs should not contain secrets by construction)
- Apply `loggers:` per-logger overrides and `silenced:` union after base setup

### `reset_logging_for_test()`

Clears `_configured`, `_loaded_config`, removes all root-logger handlers, calls `reset_correlation_id()`. Fully isolates test cases.

## Step 5 — `foundation/logging/bootstrap.py`

```python
def bootstrap(component_id: str | None = None, project_root: Path | None = None) -> str:
    """Configure logging and mint a correlation ID.

    Sets the correlation ID in the current context and returns it.
    The returned ID is already active — callers log it at startup but
    do not need to pass it further; CorrelationJsonFormatter injects it
    into every subsequent log line automatically.
    """
    configure_logging(project_root=project_root)
    return new_correlation_id()
```

Drop-in first line for every `if __name__ == "__main__"` block.

## Step 6 — `foundation/logging/audit.py`

Separate `logging.Logger("ai_audit")` with own handlers. Never mixed with diagnostic log.

```python
class AiAuditLogger:
    """No-op when ai_audit.enabled is false — zero overhead, no handlers registered."""
    def log(self, direction: str, content: str, *, provider: str, session_id: str, token_count: int | None = None) -> None: ...
```

- `direction`: `in` | `think` | `out`
- JSONL format: `{ts, provider, session_id, direction, token_count, content}`
- `TimedRotatingFileHandler(when="midnight", backupCount=7)` in `<log_dir>/ai_audit/`
- `RedactionFilter` applied — patterns: `Bearer \S+`, `sk-\w+`, `ghp_\w+`, email addresses
- `enabled=false` → `log()` is a no-op, no handler setup, zero overhead
- Global singleton `get_ai_audit_logger()` for use by harness/MCP

## Step 7 — Wire into entry points

### `launcher.py:main()`

```python
from audiagentic.foundation.logging import bootstrap
cid = bootstrap("harness", project_root=project_root)
logger.info("harness started", extra={"version": __version__, "log_level": ..., "log_dir": ..., "correlation_id": cid})
```

Add `atexit` handler logging graceful exit + uptime duration.

### All MCP server `if __name__ == "__main__"` blocks

Replace any ad-hoc logging setup with single `bootstrap(component_id)` call. Identify all blocks via:

```
grep -r 'if __name__ == "__main__"' src/audiagentic/components/optional/
```

## Step 8 — `exc_info=True` sweep

Mechanical pass across all `except` blocks that log. Verify scope first:

```
grep -rn "except" src/audiagentic/ --include="*.py" | grep -v "exc_info" | grep "logger\." | wc -l
```

Five waves:

| Wave | Scope                                                           | Approx files |
|------|-----------------------------------------------------------------|--------------|
| A    | `src/audiagentic/foundation/`                                   | ~15 files    |
| B    | `src/audiagentic/runtime/`                                      | ~20 files    |
| C    | `src/audiagentic/components/optional/ledger/`                   | ~8 files     |
| D    | `src/audiagentic/components/optional/planning/`                 | ~15 files    |
| E    | `src/audiagentic/components/optional/knowledge/`, `agent_jobs/` | ~10 files    |

## Step 9 — `log_tool_call` decorator

Single decorator in `foundation/mcp/component_server.py` supporting both sync and async:

```python
def log_tool_call(func):
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def _async_wrapper(*args, **kwargs):
            # Log tool name + correlation ID only — never log args (may contain secrets, API keys, file paths)
            logger.debug("tool call start", extra={"tool": func.__name__, "correlation_id": get_correlation_id()})
            t0 = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                logger.info("tool call done", extra={"tool": func.__name__, "duration_ms": int((time.monotonic() - t0) * 1000)})
                return result
            except Exception:
                logger.error("tool call failed", extra={"tool": func.__name__}, exc_info=True)
                raise
        return _async_wrapper
    else:
        # sync variant — same structure
        ...
```

**Do not log args or kwargs** — security decision, not an oversight. Document in the decorator docstring.

**Decorator stacking order** — `@mcp.tool()` must be outermost, `@log_tool_call` innermost:

```python
@mcp.tool()
@log_tool_call
def record_change_event(event: dict) -> dict: ...
```

This ensures FastMCP registers the `functools.wraps`-preserved wrapper (correct name + signature). The reverse order wraps a FastMCP tool object, not a function, which may silently mis-register.

Apply `@log_tool_call` to every MCP tool function in all component servers.

## Step 10 — Planning subsystem instrumentation

Target files: `item_creator.py`, `content_service.py`, `maintenance_service.py`, `idx_mgr.py`, `rec_mgr.py`, `queue_service.py`

Log points:
- `create_item` — INFO: item_id, item_type, parent_id, duration_ms
- `update_state` — INFO: item_id, old_state, new_state, duration_ms
- `propagate` — INFO: source_id, affected_count, duration_ms
- `compact` — INFO: items_compacted, bytes_freed, duration_ms
- `queue_drain` — INFO: events_processed, duration_ms

## Step 11 — Ledger instrumentation

Target files: `fragments.py`, `api.py`, `bootstrap.py`, `archive.py`, `ledger_write_mcp.py`

Log points:
- `fragment_create` — INFO: fragment_id, release_id
- `fragment_update` — INFO: fragment_id, fields_changed
- `fragment_archive` — INFO: fragment_id, reason
- `record_change_event` — INFO: event_id, component_id, duration_ms
- `bootstrap_start` — INFO: project_root
- `bootstrap_done` — INFO: duration_ms, fragments_created

## Step 12 — Install/uninstall instrumentation

`runtime/lifecycle/components.py` and `providers/services/lifecycle.py`:
- INFO on install start + completion (component_id, duration_ms)
- INFO on uninstall start + completion
- WARNING on partial failure with recovery
- ERROR + exc_info on unrecoverable failure

## Step 13 — Gitignore update

Add to project `.gitignore`:
```
.audiagentic/config/foundation/logging.local.yaml
.audiagentic/logs/
```

## Step 14 — Tests

`tests/unit/foundation/test_logging_config.py`:

- `configure_logging()` called twice → no duplicate handlers
- JSON log line parses to dict with all required keys (`ts`, `level`, `logger`, `msg`, `correlation_id`)
- `correlation_id` propagates across `asyncio.gather` tasks
- `correlation_id` propagates into `ThreadPoolExecutor` workers when context copied
- `reset_logging_for_test()` fully clears state: no handler leak, correlation ID reset to None
- Dev formatter active when `format=dev`
- File handler absent when `dir=null`
- File handler present when `dir` is set
- Config merge: project overrides global; local overrides project; env var overrides all
- `silenced:` lists are unioned across layers (not replaced)
- `loggers:` keys merge with later-layer key winning
- Malformed YAML in any tier → that tier skipped, no exception raised, process continues
- `AiAuditLogger` is no-op (no handlers, no file) when `enabled=false`
- Config discovery walk: stops at 10 levels; respects 500ms cap; result cached on second call
- `load_layered_config` `SystemExit` is caught; fallback to defaults

---

# Acceptance Criteria

- All logging files live under `foundation/logging/`; no logging logic in flat `foundation/*.py` files
- `configure_logging()` is the sole entry point for logging setup
- Zero `logging.basicConfig()` calls remain in codebase (verified by grep)
- No other module adds handlers directly to the root logger
- Config loading uses `load_layered_config` from `runtime/config/layered.py` — no custom YAML parsing
- Package default config exists at `src/audiagentic/config/provisioning/foundation/logging.yaml`
- All JSON log lines parse to valid dict matching the defined schema
- Correlation ID present in every log line after `bootstrap()` is called
- No `except` block logs without `exc_info=True` (verified by grep in CI)
- All MCP tool functions decorated with `@log_tool_call`; tool args never logged
- Planning and ledger log points fire at correct levels with defined fields
- AI audit log is a no-op (no file created, no handler registered) when `ai_audit.enabled` is false
- `.audiagentic/config/foundation/logging.local.yaml` is gitignored
- Config precedence: env var beats local beats project beats global beats defaults (test-verified)
- `silenced:` lists union across config layers (test-verified)
- `reset_logging_for_test()` isolates tests: no handler leak, no correlation ID leak

---

# Notes

- `StructuredLog` in `foundation/event/log.py` is the domain event journal (OpenTelemetry JSONL). Do not conflate with stdlib diagnostic logging. These are entirely separate systems.
- `load_layered_config` raises `SystemExit` on malformed YAML (see `runtime/config/files.py:23`). The logging wrapper must catch this — logging config must never crash the process.
- `_deep_merge` in `layered.py` replaces lists entirely. The `silenced:` union must be handled explicitly in the logging wrapper after the merge is complete, not by relying on `_deep_merge`.
- `TimedRotatingFileHandler` does not support `maxBytes`. No size cap on daily files. Risk: a log storm could fill disk. Mitigation: monitor log dir size in ops runbooks. If a day's file exceeds ~500MB, switch to `RotatingFileHandler` with a date-stamped filename pattern.
- `RedactionFilter` on diagnostic handlers is skipped for performance. If secrets appear in diagnostic logs, the fix is at the call site, not the filter.
- `dev` format ANSI colour: use `colorlog` as an optional import-guarded dep, or manual ANSI when `sys.stderr.isatty()`. Low priority.
- Lint: ruff cannot reliably detect `logger.warning()` without `exc_info` in except blocks. Add to TESTING.md code review checklist.
- `log_tool_call` args omission is a security decision — document in docstring to prevent future "fixes".
