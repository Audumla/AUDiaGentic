# Codebase refactor analysis — round 2 (post-split)

Fresh pass on the current tree (298 `.py` files, ~28.6k LOC). The round-1 plan
(`refactor-file-cleanup-plan.md`) is **fully executed and committed** — no file
now exceeds 400 lines (largest is 375). This round targets *duplication*,
*misplaced logic*, and *cross-cutting concerns* that survived the size pass.

**Plan only — nothing here is implemented.** Each item: finding → options →
execution steps → risk/test. Verify line anchors before editing (they drift).

---

## A. Duplication / logic to consolidate

### A1 — `_project_root()` copy-paste vs existing foundation helper  ★ HIGH value, LOW risk
**Finding:** `foundation/mcp/component_server.py:105` already exports
`project_root_from_env()` = `Path(os.environ.get("AUDIAGENTIC_REPO_ROOT",".")).resolve()`.
Yet these MCP modules each redefine the **identical** one-liner under a local
name (`_project_root` / `_resolve_project_root`):
- `components/optional/ledger/ledger_mcp.py`
- `components/optional/ledger/ledger_manage_mcp.py`
- `components/optional/release/release_mcp.py`
- `components/optional/release/release_please/release_please_mcp.py`
- `components/optional/coding_lsp/lsp_manage_mcp.py`
- `components/optional/providers/providers_mcp.py`

**EXCLUDE** (different logic — cwd/layered walk, not the env one-liner; do NOT
merge): `foundation/logging/config.py:_resolve_project_root`,
`runtime/harness/pi/install/config.py`, `runtime/harness/opencode/install/__init__.py`.
Read each before touching to confirm it's the env one-liner.

**Options:**
- **(a) Recommended:** delete each local copy; import `project_root_from_env`
  from `foundation.mcp.component_server`; rename call sites. One canonical name.
- (b) Leave as-is. (Rejected — 6 copies of a function that already exists.)

**Steps:** per file — remove local def; add
`from audiagentic.foundation.mcp.component_server import project_root_from_env`;
replace `_project_root()` / `_resolve_project_root()` calls. Confirm the call
arity matches (all are zero-arg).
**Risk:** none (identical impl). **Test:** `pytest tests/ -q -k "mcp or ledger or release or lsp"`; import-smoke each module.

### A2 — MCP server `build_server` boilerplate  ★ MEDIUM value
**Finding:** `project_mcp.py`, `session_mcp.py`, `providers_mcp.py` each define a
duplicated trio `_server_instructions()` / `_tool_description(name)` /
`_report_error(name, exc)`, and every tool repeats the same shape:
```python
@mcp.tool(description=_tool_description("x"))
@log_tool_call
def x(...):
    try: return api.x(project_root_from_env())
    except Exception as exc: return _report_error("x", exc)
```
`foundation/mcp/component_server.py` already centralizes `log_tool_call`,
`mcp_server()`, `project_root_from_env()` — but not the error/description/
instructions helpers.

**Options:**
- **(a) Recommended:** move `_tool_description` + `_report_error` (and an
  instructions loader) into `foundation/mcp/component_server.py`; the 3 modules
  import them. Optionally add a `guarded_tool` decorator that folds the
  `try/except → report_error` into the existing `log_tool_call` so each tool body
  drops its boilerplate.
- (b) Move only the trio (no decorator) — smaller change, leaves per-tool
  try/except. Lower payoff.
- (c) Leave. (Rejected — 3× duplication and growing per new MCP component.)

**Steps:** (a) add helpers to `component_server.py`; verify `_tool_description`
reads the same description source in all 3 (check it isn't per-module hardcoded
text); replace local defs with imports; if adding `guarded_tool`, migrate one
module first, run its tests, then the others.
**Risk:** medium — error-envelope shape must stay byte-identical (MCP clients
parse it). Snapshot one error response before/after.
**Test:** `pytest tests/ -q -k "mcp"`; manually invoke one tool to diff the error envelope.

### A3 — Provider surface renderers are ~9 near-identical single-file writers  ★ MEDIUM value, spread
**Finding:** 12 `adapters/*/surface.py` each define `render_contributions` +
`render`. Most just emit a `## {title}\n\n{body}` block into one markdown file,
differing only by filename:
- AGENTS.md: aider, opencode, goose, openhands, plandex, codex (codex 63L — check
  for extras)
- GEMINI.md: gemini · COPILOT.md: copilot · QWEN.md: qwen
- **Bespoke (keep):** claude (`.claude/rules/*` vs CLAUDE.md branching),
  cline, roo (no markdown target — VS Code extensions).

**Options:**
- **(a) Recommended:** add `make_single_file_renderer(filename)` (+ matching
  `make_single_file_contribution_renderer`) to the surfaces base module; collapse
  the ~9 clone surfaces to a 2–3 line registration each. Keep claude/cline/roo
  custom. ~9 files shrink to near-trivial.
- (b) Factory only for the exact AGENTS.md group (6), leave the
  GEMINI/COPILOT/QWEN trio. Smaller blast radius.
- (c) Leave — they're per-provider by design. (Weak: the per-provider part is
  just a filename; the logic is copy-paste.)

**Steps:** locate the surfaces base (`providers/surfaces/base.py` or
`skill_surfaces.py`); add factory; per clone surface replace both functions with
`render = make_single_file_renderer("AGENTS.md")` + existing `register_*` calls;
diff codex first (it's larger — may carry extra blocks).
**Risk:** medium — output files are user-facing (AGENTS.md etc.). Generate before/
after for one provider and diff exact bytes.
**Test:** `pytest tests/ -q -k "surface or contribution or render"`; surface-apply smoke if available.

---

## B. Cross-cutting files to split (mixed concerns, <400 but confused)

### B1 — `runtime/lifecycle/components.py` (362)  ★ MEDIUM
**Finding:** two concerns. Component lifecycle (install/uninstall/enable/disable
+ marker helpers, lines 41–268) **and** MCP propagation
(`_refresh_mcp_config_if_needed` 269, `_propagate_mcp_to_providers` 288,
`sync_all_provider_mcp_servers` 341 — ~93 lines).
**Option (a, recommended):** extract the MCP-propagation block →
`runtime/lifecycle/component_mcp.py`; re-export the public
`sync_all_provider_mcp_servers` from `components.py`. Lifecycle calls into it.
**Steps:** move 3 funcs; `components.py` imports them; re-export rule; watch a
cycle (component_mcp imports descriptor/provider sync that may import lifecycle →
lazy-import if so). **Test:** `pytest tests/ -q -k "component or lifecycle or mcp"`.

### B2 — `components/optional/coding_lsp/lsp_api.py` (315)  ★ MEDIUM
**Finding:** LSP *operations* (workspace_symbols/definition/hover/references/
diagnostics/rename + `_open_file_session`/`_resolve_language_server`, lines
84–142 & 284–313) mixed with *language/dependency config management*
(`config_status` 166, `add_language` 195, `remove_language` 208, `list_languages`
221, `install_lsp_dependencies` 234, `list_missing` 273 + `_configured_*`/
`_*dependency*` helpers).
**Option (a, recommended):** extract the config/dependency half →
`lsp_config_api.py`; keep the LSP operations in `lsp_api.py`; re-export moved
public names. The MCP wrapper `lsp_manage_mcp.py` already separates these calls,
so the seam matches the existing tool grouping.
**Risk:** low — clean functional boundary. **Test:** `pytest tests/ -q -k "lsp"`.

### B3 — `runtime/harness/...` MCP config I/O trio  ★ INVESTIGATE (don't assume)
**Finding:** `read_mcp_config` / `write_mcp_config` / `remove_mcp_config` /
`mcp_config_path` defined 3× (`harness/__init__.py`, `harness/pi/install/__init__.py`,
`harness/opencode/install/__init__.py`).
**Action first:** diff the three impls. If they're per-harness format variants
(pi vs opencode JSON shapes) the duplication is *structural*, not accidental —
then the fix is a shared helper taking a format/spec, not a blind merge. If
they're identical, consolidate into `harness/mcp_config.py`.
**Option (a):** shared `mcp_config.py` with a format param; (b) leave if genuinely
divergent. **Test:** `pytest tests/ -q -k "harness and mcp"`.

---

## C. Lower-priority / watch list (no action unless touched)

- **`.audiagentic` path literals** scattered ~30× (e.g. `…/runtime/ledger/
  fragments` ×5, `…/runtime/jobs` ×3). Option: a `foundation/paths` constants/
  builder module (one exists — extend it). High churn, low urgency; do
  opportunistically when editing a path-heavy module. Risk: easy to typo a path
  during migration — migrate one subtree at a time with tests.
- **`foundation/workflow/invocation/steps.py` (280)** — 7 `*Step` classes
  implementing one Protocol. Cohesive strategy family; a `steps/` package is
  possible but offers little. **Leave.**
- **`foundation/event/event_bus.py` (296)** — single `EventBus` class (~200L),
  one responsibility. **Leave.**
- **`provider_streaming.py` (317)** — sink builders + run loop, one domain.
  **Leave** unless it grows.

---

## D. Execution order & batching
1. **A1** (project-root dup) — trivial, do first; removes 6 copies.
2. **A2** (MCP boilerplate) — after A1 (both touch the MCP modules; sequencing
   avoids re-editing). Migrate one module, verify error envelope, then the rest.
3. **B2** (lsp split) and **B1** (components split) — independent, low risk.
4. **B3** — investigate first; only consolidate if impls match.
5. **A3** (surface factory) — biggest file-count touch; do as its own batch with
   byte-diff verification of generated markdown.
6. **C** items — opportunistic only.

**Per item:** `ruff check <files>` + the listed pytest selector green → one
commit → `ag-ledger` `record_change_event` (class `refactor`, status
`unreleased`). Use git MCP tools, not raw git. Do not edit release artifacts.

## E. Explicitly rejected
- Merging the cwd-walking `_resolve_project_root` in logging/install into A1
  (different logic).
- Splitting `event_bus.py`, `steps.py`, `provider_streaming.py` (cohesive).
- Blind merge of B3 before diffing (may be intentional per-harness variants).
