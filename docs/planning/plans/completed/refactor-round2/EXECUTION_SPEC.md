# Round-2 refactor — execution spec

Audience: an agent executing cold. Companion to `refactor-analysis-round2.md`
(the rationale). This file is the **how**: exact files, line anchors, import
edits, tests, gotchas. Line anchors drift — re-grep the `def` before editing.

## Ground rules (every item)
- **Behavior-preserving** unless an item says otherwise. No public signature or
  return-shape change.
- **Current-state rule:** this spec predates some accepted surface changes in the
  repo (for example `session` MCP now exposes `update_rig(scope=...)`, provider
  summary/detail status paths were split for performance, and layered path
  resolution now lives in `src/audiagentic/foundation/paths/resolution.py`).
  Before editing any referenced module, re-grep the current function/tool names
  and confirm the live contract rather than assuming the examples below are the
  exact current signatures.
- **No compatibility rule:** do not add re-exports, compatibility wrappers,
  legacy handlers, or dual-path support. If symbol `X` moves, update all imports
  and call sites to the new canonical module and delete the old access path.
- **Cycle rule:** if a move causes circular import, lazy-import inside the
  function. Reference: `agent_jobs/prompt_launch.py` ↔ `review_launch.py`.
- **Gate per item:** `python -m ruff check <files>` + the item's pytest selector,
  both green, before commit. One item = one commit.
- **Ledger:** after each item, `ag-ledger` `record_change_event` (class
  `refactor`, status `unreleased`). Git via MCP tools, not raw git. Never edit
  release artifacts.
- **Baseline note:** the earlier `tests/integration/jobs/test_prompt_launch_flow.py`
  fixture-path drift has been fixed. Treat failures there as real regressions,
  not known baseline noise.

Recommended order: **A1 → A2 → B2 → B1 → A3**. (B3 is investigate-only; C is
opportunistic.) A1 first because A2 touches the same MCP modules.

---

## A1 — Replace 6 copied `_project_root()` with `project_root_from_env`  ★ HIGH / LOW risk
**Canonical helper (already exists):**
`audiagentic.foundation.mcp.component_server.project_root_from_env()` →
returns `Path(os.environ["AUDIAGENTIC_REPO_ROOT"])` when set, otherwise raises
`RuntimeError("AUDIAGENTIC_REPO_ROOT not set")`. The 6 local `_project_root()`
copies match that fail-fast behavior today.

**Edit these 6 files** (each has a zero-arg `def _project_root() -> Path:` that is
the identical one-liner, and already imports from `component_server`):

| File | `_project_root` def | call sites |
|---|---|---|
| `components/optional/ledger/ledger_mcp.py` | L13 | L27,34,41,48 |
| `components/optional/ledger/ledger_manage_mcp.py` | L13 | L21 |
| `components/optional/release/release_mcp.py` | L13 | L21,28 |
| `components/optional/release/release_please/release_please_mcp.py` | L14 | L27,34,41 |
| `components/optional/coding_lsp/lsp_manage_mcp.py` | L18 | L49,58 |
| `components/optional/providers/providers_mcp.py` | L25 | L55,60,70,76,86,95,106,117,128,138,148,159 |

**Per file:**
1. Delete the local `def _project_root(): ...`.
2. Add `project_root_from_env` to the existing
   `from audiagentic.foundation.mcp.component_server import (...)` line.
3. Replace every `_project_root()` call with `project_root_from_env()`.
4. If `import os` is now unused (`grep -n "os\." <file>` → empty), remove it.

**DO NOT TOUCH** (different logic — param + cwd/layered walk, confirmed):
`foundation/logging/config.py:_resolve_project_root`,
`runtime/harness/pi/install/config.py:_resolve_project_root`,
`runtime/harness/opencode/install/__init__.py`.

**Risk:** none (identical impl). **Test:**
`python -m ruff check <6 files>` then
`python -m pytest tests/ -q -k "ledger or release or lsp or providers_mcp or mcp"`
plus `python -c "import audiagentic.components.optional.ledger.ledger_mcp"` (repeat per module).

---

## A2 — Hoist MCP server helper trio into `component_server.py`  ★ MEDIUM-LOW (optional)
**Scope:** `project_mcp.py` and `session_mcp.py` only. **Exclude `providers_mcp.py`**
— although it has `_server_instructions` / `_tool_description`, it has no
`_report_error` and most of its tool surface is built around
`run_blocking_with_output` (different style / lower payoff for this extraction).

**Current duplication** (in `components/core/project/project_mcp.py` and
`components/core/session/session_mcp.py`):
```python
def _server_decl():                         # module-specific, KEEP local
    return get_mcp_server_declaration(COMPONENT_X, "ag-x-mgmt")
def _server_instructions() -> str:          # identical in both
    decl = _server_decl(); return decl.instructions if decl else ""
def _tool_description(name) -> str:         # identical logic in both
    decl = _server_decl(); return decl.tool_descriptions.get(name, "") if decl else ""
def _report_error(tool_name, exc) -> dict:  # differs only by log label
    logger.exception("project tool failed: %s", tool_name)   # vs "session tool failed"
    return {"ok": False, "error": str(exc), "tool": tool_name}
```

**Add to `foundation/mcp/component_server.py`:**
```python
def server_instructions(decl) -> str:
    return decl.instructions if decl else ""
def tool_description(decl, name: str) -> str:
    return decl.tool_descriptions.get(name, "") if decl else ""
def report_error(label: str, tool_name: str, exc: Exception) -> dict[str, Any]:
    logging.getLogger(__name__).exception("%s tool failed: %s", label, tool_name)
    return {"ok": False, "error": str(exc), "tool": tool_name}
```
If logger attribution must remain module-local, pass a logger or logger name into
`report_error(...)` rather than hard-wiring `component_server` as the emitter.
**Per module:** keep `_server_decl()`; replace the 3 local helpers with direct
shared calls or small local helpers only if they still add real value. Do not
add wrapper-for-wrapper compatibility layers. Pass the label
(`"project"`/`"session"`) into `report_error`.

**Decision options:**
- (a) Helpers only (above) — minimal, recommended.
- (b) Also add a `guarded_tool(label)` decorator folding the per-tool
  `try/except → report_error` into `log_tool_call`. Higher payoff, higher risk
  (every tool body changes). Only if you migrate + test one module first.

**Risk:** MEDIUM — the error dict `{"ok","error","tool"}` is MCP-client-facing.
Keep it byte-identical; the log message text may change (cosmetic) but confirm no
test asserts the exact log string.
**Test:** `python -m pytest tests/ -q -k "project_mcp or session_mcp or mcp"`;
invoke one tool to force an error and diff the returned dict.

---

## B2 — Split `lsp_api.py` (315) → operations vs config/dependency  ★ MEDIUM / LOW risk
**File:** `components/optional/coding_lsp/lsp_api.py`. Clean seam — ops-half never
calls config-half (verified); config-half is self-contained.

**Create `lsp_config_api.py`, MOVE these (config/dependency management):**
`_configured_language_ids` (L143), `configured_dependency_ids` (L152),
`missing_configured_dependencies` (L157), `config_status` (L166),
`add_language` (L195), `remove_language` (L208), `list_languages` (L221),
`install_lsp_dependencies` (L234, `async`), `list_missing` (L273).
Move their imports too (`language_registry`, `detect_missing`, etc.).

**KEEP in `lsp_api.py` (LSP protocol ops):** `_sync_to_providers`,
`shutdown_all_sessions`, `parse_position`, `file_to_uri`, `resolve_project_root`,
`discover_servers`, `workspace_symbols`, `document_symbols`, `definition`,
`hover`, `references`, `diagnostics`, `rename_preview`, `_open_file_session`,
`_resolve_language_server`, `_lang_to_id`.

**Importer update (no compatibility path):**
update every caller to import from `lsp_config_api.py` directly. After imports
and call sites are updated, remove the moved symbols from `lsp_api.py`.

**Cycle check:** if `lsp_config_api` needs an ops-half symbol, lazy-import it
inside the function (none expected — config-half is self-contained).
**Test:** `python -m ruff check <2 files>` +
`python -m pytest tests/ -q -k "lsp"` + import-smoke `lsp_manage_mcp`,
`coding_lsp_bootstrap`.

---

## B1 — Split `lifecycle/components.py` (362) → extract MCP propagation  ★ MEDIUM
**File:** `runtime/lifecycle/components.py`.

**Create `runtime/lifecycle/component_mcp.py`, MOVE:**
`_refresh_mcp_config_if_needed` (L269), `_propagate_mcp_to_providers` (L288),
`sync_all_provider_mcp_servers` (L341). Move their imports.

**KEEP in `components.py`:** all install/uninstall/enable/disable + marker/result
helpers (L41–268). Wherever `components.py` calls
`_refresh_mcp_config_if_needed` (inside install/uninstall paths), import it from
`.component_mcp`.

**Importer update:** update every caller to import
`sync_all_provider_mcp_servers` from `runtime/lifecycle/component_mcp.py`
directly, then remove the old symbol from `components.py`.

**Cycle risk:** `component_mcp` will import provider-sync / descriptor helpers that
may pull `components`. If `ruff`/collection shows a cycle, lazy-import those
inside the 3 functions (they already do filesystem/registry work, so lazy is fine).
**Test:** `python -m pytest tests/ -q -k "component or lifecycle or reconcile or mcp"`.

---

## A3 — Factory for clone `render_contributions` surfaces  ★ MEDIUM / spread
**Important scope correction:** only `render_contributions` is duplicated. The
sibling `render` functions differ substantially (gemini/cline build skill
surfaces; goose returns `{}`) — **do NOT touch `render`**.

**Add to `components/optional/providers/surfaces/base.py`:**
```python
def make_single_file_contribution_renderer(filename: str, *, heading: str = "##"):
    def render_contributions(*, project_root, contributions):
        return [
            SurfaceBlock(
                path=project_root / filename,
                block_id=c.contribution_id,
                content=f"{heading} {c.title}\n\n{c.body.strip()}",
            )
            for c in contributions
        ]
    return render_contributions
```
Before converting any surface, verify the registered caller invokes
`render_contributions` with keyword arguments (`project_root=...`,
`contributions=...`). If any positional call sites exist, either update them in
the same item or keep the factory signature compatible with the live call
pattern.

**Convert these surfaces** — replace the whole `render_contributions` def with a
factory call, keep their `render` + both `register_*` lines:
| provider | file target | notes |
|---|---|---|
| aider | `AGENTS.md` | comprehension form today |
| opencode | `AGENTS.md` | |
| goose | `AGENTS.md` | `render` returns `{}` |
| openhands | `AGENTS.md` | |
| plandex | `AGENTS.md` | |
| codex | `AGENTS.md` | **diff first** (63L — may carry extra blocks) |
| gemini | `GEMINI.md` | loop form today |
| copilot | `COPILOT.md` | |
| qwen | `QWEN.md` | |

Pattern per file:
```python
render_contributions = make_single_file_contribution_renderer("AGENTS.md")
...
register_contribution_renderer("goose", render_contributions)
```

**KEEP BESPOKE (do not convert):**
- `claude` — branches `.claude/rules/<id>.md` (raw body) vs `CLAUDE.md` (`##`).
- `cline` — branches `.clinerules/<id>.md` vs `.clinerules/audiagentic.md`, uses
  `#` (h1) heading.
- `roo` — no markdown target.

**Risk:** MEDIUM — output is user-facing managed markdown. For one AGENTS.md
provider and one `X.md` provider: capture generated blocks before/after and diff
exact bytes (heading level, spacing, block_id). Confirm `make_*` lives where the
surfaces import base from (`...surfaces.base`).
**Test:** `python -m pytest tests/ -q -k "surface or contribution or render"` +
surface-apply smoke if available
(`python -m audiagentic.components.optional.providers.skill_surfaces --project-root .`).

---

## B3 — Harness MCP-config trio: INVESTIGATE, do NOT mechanically merge
`read_mcp_config` / `write_mcp_config` / `remove_mcp_config` / `mcp_config_path`
exist in `runtime/harness/__init__.py`, `harness/pi/install/__init__.py`,
`harness/opencode/install/__init__.py`. **All 12 impls hash differently** — they
are per-harness format variants (pi vs opencode config shapes), not accidental
copies. A blind merge would break a harness.
**Only if** you do a deliberate design pass: introduce a format-spec object and a
single spec-driven helper in `harness/mcp_config.py`, migrating one harness at a
time with its tests. Otherwise **leave as-is.** Not a mechanical refactor.

---

## C / watch-list (opportunistic only, no standalone batch)
- Scattered `.audiagentic` path literals (~30×) → extend `foundation/paths`
  builder; migrate one subtree at a time with tests. High churn, low urgency.
- Leave (cohesive): `event_bus.py`, `invocation/steps.py`, `provider_streaming.py`.

## Done-criteria per item
ruff clean · listed pytest selector green · import-smoke of touched modules ·
one commit · ledger event recorded.
