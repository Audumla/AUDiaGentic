# File cleanup — execution spec

Audience: an engineer/agent doing the work cold. Every item lists exact files,
line anchors, the seam, import edits, re-export plan, test command, and known
gotchas. **Do items in order. One item = one commit. Run the item's test before
committing.**

## Ground rules (apply to every item)
- **Behavior-preserving.** No public function signature or return shape changes
  unless the item says so explicitly.
- **Re-export rule.** When you move a symbol out of module `M` into new module
  `N`, add `from .N import <names>` (or absolute equivalent) back into `M` so
  every existing import path keeps resolving. Verify with
  `grep -rn "import <name>" src tests`.
- **Import-cycle rule.** If a re-export creates a circular import (ImportError at
  collection), convert the back-reference to a **lazy import inside the function**
  that needs it. Reference implementation already in the tree:
  `src/audiagentic/components/optional/agent_jobs/prompt_launch.py`
  (`launch_prompt_request` lazy-imports `review_launch`) and
  `review_launch.py` (`_build_and_persist_review` lazy-imports `prompt_launch`).
- **Lint+test gate per item:** `python -m ruff check <changed files>` then the
  item's pytest selector. Both green before commit.
- **Source control:** use the repo MCP git tools, not raw `git` (CLAUDE.md).
- **Ledger:** after each item (or a small batch), record a `refactor` change
  event via the `ag-ledger` `record_change_event` MCP tool (required fields:
  change-class, files, technical-summary, user-summary-candidate, status
  `unreleased`).

## ⚠ Known pre-existing failure — DO NOT chase
`tests/integration/jobs/test_prompt_launch_flow.py` has 3 tests that fail on a
clean `HEAD` (reproduced via stash). Cause: the test fixture writes
`.audiagentic/providers.yaml` + `.audiagentic/project.yaml`, but the loaders now
read `.audiagentic/config/runtime/providers.yaml` (+ `config/project.yaml`).
This is unrelated to every item below **except Item 0**, which fixes it. If you
are not doing Item 0, treat those 3 reds as baseline.

---

## Item 0 — Fix pre-existing provider-config fixture drift
**Goal:** make `test_prompt_launch_flow.py` green so later items have a clean baseline.

**File:** `tests/integration/jobs/test_prompt_launch_flow.py`, function
`_write_project_and_provider_config` (around lines 21–99).

**Problem:** it writes to `sandbox.repo/.audiagentic/project.yaml` and
`sandbox.repo/.audiagentic/providers.yaml`. The code under test resolves:
- project config: `load_project_config` → `.audiagentic/config/project.yaml`
  (see `prompt_launch.load_project_config`).
- provider config: `load_provider_config` → `.audiagentic/config/runtime/providers.yaml`
  (see `providers/services/provider_config.py:load_provider_config`, error
  `VAL-PCFG-001`).

**Steps:**
1. Open `provider_config.py` and `prompt_launch.load_project_config`; confirm the
   exact expected paths (do not assume — read them).
2. Update the fixture to write each YAML to the path the loader actually reads
   (create parent dirs). Keep the YAML bodies as-is (they are valid).
3. `python -m pytest tests/integration/jobs/test_prompt_launch_flow.py -q` → all pass.

**Gotcha:** there may be two loaders (project vs provider) with different roots;
fix both. Do not change the YAML content, only the destination paths.

---

## Item A1 — Delete `streaming/_utils.py`, use `foundation.time`
**Why:** `_utc_now()` is byte-for-byte `foundation.time.now_iso_z("microseconds")`.

**Delete:** `src/audiagentic/components/optional/providers/protocols/streaming/_utils.py`

**Edit 3 callers** — replace the import line and each call:
- `.../streaming/base_extractor.py`: line 6 import; call at line 52.
- `.../streaming/completion.py`: line 13 import; call at line 94.
- `.../streaming/sinks.py`: line 15 import; calls at lines 206, 244.

In each: change
`from audiagentic.components.optional.providers.protocols.streaming._utils import _utc_now`
→ `from audiagentic.foundation.time import now_iso_z`
and every `_utc_now()` → `now_iso_z("microseconds")`.

**Verify no stragglers:** `grep -rn "_utc_now\|streaming._utils" src tests` → empty.
**Test:** `python -m pytest tests/ -q -k "stream or sink or completion or extractor"`
**Gotcha:** none. Output string is identical.

---

## Item A2 — Dedup `services/mcp.py` sync pair
**File:** `src/audiagentic/components/optional/providers/services/mcp.py`
- `sync_managed_provider_mcp` (lines 161–248)
- `sync_managed_provider_mcp_subset` (lines 250–346)

**Fact:** the two bodies are identical except the subset variant:
1. takes `*, managed_ids: set[str]`,
2. in the removal loop iterates a `targeted_existing` dict (registry filtered to
   `managed_ids`) instead of the full `provider_registry`,
3. in the apply loop adds `if managed_id not in managed_ids: continue`.

**Refactor:** add a private
`def _sync_managed_entries(provider_id, project_root, desired_entries, *, managed_ids: set[str] | None = None)`
holding the shared body. Behavior switch:
- removal loop source = `provider_registry.items()` if `managed_ids is None`
  else `{mid: name for mid, name in provider_registry.items() if mid in managed_ids}`.
- apply loop: `if managed_ids is not None and managed_id not in managed_ids: continue`.

Then the two **public** functions become one-line wrappers (keep names/signatures):
- `sync_managed_provider_mcp(...)` → `return _sync_managed_entries(provider_id, project_root, desired_entries)`
- `sync_managed_provider_mcp_subset(..., *, managed_ids)` → `return _sync_managed_entries(..., managed_ids=managed_ids)`

**Keep file and both public names** (do not split into a new file — pure dedup).
**Test:** `python -m pytest tests/ -q -k "mcp and (sync or managed or reconcile)"`
**Gotcha:** preserve exact result-dict keys/order of `updated`/`removed` lists —
they are assembled by append; don't reorder logic.

---

## Item A3 — Consolidate stub adapter bodies into a shared helper
**Constraint (critical):** the adapter loader resolves
`audiagentic.components.optional.providers.adapters.<id>.adapter` and calls its
`run` (see `providers/services/execution.py:_adapter_module_path` / `_load_runner`).
**You must keep each `adapter.py` file** — deleting them breaks dispatch. Goal is
to remove duplicated *bodies*, not files.

**New file:** `src/audiagentic/components/optional/providers/adapters/_stubs.py`

The 7 stubs fall into 3 behaviors (verified):
| provider id | dir | status | extra |
|---|---|---|---|
| goose | goose | stubbed | `require_executable("goose","goose")`; msg "Goose adapter is registered; execution bridge not wired yet." |
| aider | aider | stubbed | `require_executable("aider","aider")`; msg "Aider adapter is registered; execution bridge not wired yet." |
| openhands | openhands | stubbed | `require_executable("openhands","openhands")`; msg "OpenHands adapter is registered; sandbox execution bridge not wired yet." |
| plandex | plandex | stubbed | `require_executable("plandex","plandex","pdx")`; msg "Plandex adapter is registered; execution bridge not wired yet." |
| continue | continue_ | ok | no probe; output "stubbed-response" |
| local-openai | local_openai | ok | no probe; output "stubbed-response"; provider-id from `packet_ctx.get("provider-id") or "local-openai"` |
| roo | roo | (raises) | **leave file untouched** — distinct `AudiaGenticError` code `CON-ROO-001` |

`require_executable(provider_id, *aliases)` is in `adapters/cli.py`.

**Helper design (`_stubs.py`):**
```python
def make_probe_stub(provider_id, *aliases, message, access_mode_default="cli"):
    def run(packet_ctx, provider_cfg):
        return {
            "provider-id": provider_id,
            "status": "stubbed",
            "execution-mode": provider_cfg.get("access-mode", access_mode_default),
            "model": provider_cfg.get("default-model"),
            "executable": require_executable(provider_id, *aliases),
            "output": message,
        }
    return run

def make_ok_stub(default_provider_id, *, derive_id_from_ctx=False):
    def run(packet_ctx, provider_cfg):
        pid = (packet_ctx.get("provider-id") or default_provider_id) if derive_id_from_ctx else default_provider_id
        return {"provider-id": pid, "status": "ok",
                "model": provider_cfg.get("default-model"), "output": "stubbed-response"}
    return run
```
Then each stub `adapter.py` becomes (preserve module docstring):
- goose: `run = make_probe_stub("goose", "goose", message="Goose adapter is registered; execution bridge not wired yet.")`
- aider/openhands/plandex: same pattern with their aliases + messages (plandex passes `"plandex","pdx"`).
- continue_: `run = make_ok_stub("continue")`
- local_openai: `run = make_ok_stub("local-openai", derive_id_from_ctx=True)`
- **roo: no change.**

**Do NOT change `status` values** — `continue`/`local-openai` MUST stay `"ok"`;
tests `tests/integration/providers/test_continue.py:18` and
`test_local_openai.py:18` assert it. `test_local_openai.py` also asserts the
qwen alias path (`provider-id` echoed from ctx) — that's why `local_openai` uses
`derive_id_from_ctx=True`.

**Test:** `python -m pytest tests/integration/providers/test_continue.py tests/integration/providers/test_local_openai.py tests/integration/providers/test_goose.py -q`
(plus any per-provider adapter tests under `tests/` — `grep -rln "adapters.\(aider\|openhands\|plandex\)" tests`).
Most provider integration tests are Docker-gated and will SKIP locally; the
continue/local_openai/qwen contract tests run unconditionally — they are the gate.
**Gotcha:** `require_executable` raises if the binary is absent. Keep it inside
`run` (lazy, per-call) exactly as today — do not call it at import time.

---

## Item B1 — Delete dead `runner/constants.py`
**File:** `src/audiagentic/runtime/harness/pi/runner/constants.py` (4 lines,
re-exports `_HARNESS_CONFIG, _RIG_CONFIG` from `harness.paths`).
**Importers:** none (`grep -rn "runner.constants\|runner import constants\|from .constants" src tests` → empty). 
**Step:** delete the file. **Test:** `python -m pytest tests/ -q -k harness` and
`python -c "import audiagentic.runtime.harness.pi.runner"`.

## Item B2 — Delete `pi/system_md.py` shim
**File:** `src/audiagentic/runtime/harness/pi/system_md.py` (9-line shim
re-exporting from `harness.system_prompt` under `*_system_md_*` aliases).
**Live importers:** only `tests/unit/provisioning/test_dynamic_agent_config.py`
(production `install/config.py` already imports from `harness.system_prompt`
directly — confirmed at `install/config.py:_build_system_md`, lines ~144–148).
**Steps:**
1. `grep -rn "system_md" src tests` — for each hit, repoint to
   `audiagentic.runtime.harness.system_prompt` using the real names
   (`apply_system_prompt_injections`, `build_system_prompt_injections`),
   aliasing locally if the test relies on the `*_system_md_*` names.
2. Delete `system_md.py`.
**Test:** `python -m pytest tests/unit/provisioning/test_dynamic_agent_config.py -q`.

## Item B3 — Merge `workflow/item.py` `ItemView` into `interfaces.py`
**Move:** the `ItemView` dataclass (entire `workflow/item.py`, 15 lines) into
`src/audiagentic/foundation/workflow/interfaces.py` (it already imports ItemView
and holds the sibling contracts `WorkflowConfig`/`WorkflowContext`).
**Edit importers of `.item`:**
- `foundation/workflow/interfaces.py:15` — delete `from .item import ItemView`
  (now defined locally; place the dataclass above its first use).
- `foundation/workflow/state_machine.py:16` — `from .item import ItemView`
  → `from .interfaces import ItemView`.
- `foundation/workflow/__init__.py:11` — `from .item import ItemView`
  → `from .interfaces import ItemView`.
**Delete:** `workflow/item.py`.
**Keep** `__init__.py` `__all__` unchanged (public seam stable).
**Gotcha:** `ItemView` needs `from dataclasses import dataclass`, `from pathlib
import Path`, `from typing import Any` — ensure `interfaces.py` has them.

## Item B4 — Merge `workflow/rel.py` `Relationships` into `util.py`
**Move:** the `Relationships` class (entire `workflow/rel.py`, 16 lines) into
`src/audiagentic/foundation/workflow/util.py`.
**Edit importer:** `foundation/workflow/__init__.py:13`
`from .rel import Relationships` → `from .util import Relationships`.
Add `Relationships` to `util.py.__all__`.
**Delete:** `workflow/rel.py`.
**Test (B3+B4):** `python -m pytest tests/unit/foundation/workflow/ -q`
(esp. `test_frontmatter_rel_util.py`, which imports `Relationships` via the
package and `util` helpers — must stay green).

---

## Tier C — Splits (>400 lines, logical seam). Method is identical for each:
1. Create new module(s); **move** the listed functions/classes verbatim.
2. Add needed imports to the new module; **re-export** moved names from the
   original module (Re-export rule) so external importers don't break.
3. If a cycle appears, lazy-import (Import-cycle rule).
4. `ruff check` + run the file's tests. Commit. Ledger.

Before moving any *public* (non-underscore) symbol, run
`grep -rn "import <name>" src tests` and make sure the re-export keeps them
resolving.

### C1 — `runtime/harness/pi/install/patches.py` (634)
- New `patches_mcp_progress.py` ← `_patch_mcp_direct_tools_progress` (253–467)
  + `_patch_mcp_proxy_progress` (468–581).
- New `patches_mcp_register.py` ← `_patch_mcp_direct_tools_live_register` (184–252).
- **Keep** the 6 smaller `_patch_*` and `apply_lockdown_patches` (613–end) in
  `patches.py`. `apply_lockdown_patches` calls the moved functions → add
  `from .patches_mcp_progress import ...` / `from .patches_mcp_register import ...`
  at the top of `patches.py`.
- Check the moved functions' own helper deps (shared module-level helpers/regex
  in patches.py) — move or import them too.
- **Test:** `python -m pytest tests/ -q -k "patch or lockdown"`.

### C2 — `foundation/logging/config.py` (486)
- New `foundation/logging/formatters.py` ← classes `_CorrelationJsonFormatter`
  (296), `_DevFormatter` (334), `_ConsoleFormatter` (348),
  `_SafeTimedRotatingFileHandler` (375–401).
- **Keep** dataclasses (`DiagnosticConfig`/`AiAuditConfig`/`LoggingConfig`),
  all `_*load*`/`_*config*` loaders, `load_logging_config`, `configure_logging`,
  `reset_logging_for_test` in `config.py`.
- `configure_logging` (402) instantiates the formatters/handler → import them
  from `.formatters`.
- **Test:** `python -m pytest tests/ -q -k "log"`.

### C3 — `launcher.py` (482)
- New package `commands/` (`__init__.py`):
  - `commands/component.py` ← `_cmd_component` (67–182)
  - `commands/provider_prompt.py` ← `_try_provider_prompt` (188–262)
  - `commands/launch.py` ← `_cmd_launch` (263–347)
- **Keep** `_status`, `_cmd_install`, `_cmd_update`, `main` in `launcher.py`.
  `main` dispatches to the moved commands → import them.
- Move each command's private helpers/imports with it; watch for shared
  module-level constants in `launcher.py`.
- **Test:** `python -m pytest tests/ -q -k "launch or cli or command"` and
  `python -m audiagentic --help` (smoke).

### C4 — `runtime/rig/embedded/launch.py` (472)
- New `embedded/resolution.py` ← path/model resolvers: `runtime_bin_dir` (59),
  `resolve_under` (71), `ensure_under` (79), `find_server_bin` (87),
  `resolve_model` (117), `_layered_model_candidates` (146),
  `_first_existing_model` (165), `_project_audiagentic_root` (172).
- New `embedded/cli.py` ← `_apply_cli_overrides` (199), `print_result` (185),
  `parse_args` (443), `main` (462), `launch_background` (388),
  `launch_foreground` (407).
- **Keep** `LaunchResult`, `LaunchPlan`, `prepare_launch` (214),
  `start_embedded_rig` (263) in `launch.py`.
- `prepare_launch`/`start_embedded_rig` call the resolvers → import from
  `.resolution`; `cli.py` imports `prepare_launch`/`start_embedded_rig` from
  `.launch`. If `launch.py` ↔ `cli.py` both top-import each other, lazy-import in
  `cli.main`. Preserve the `embedded.launch:main` entry point (re-export `main`
  from `launch.py` if anything calls `embedded.launch.main`; check
  `grep -rn "embedded.launch import\|embedded\.launch\b" src tests` first).
- **Test:** `python -m pytest tests/ -q -k "embedded or rig"`.

### C5 — `components/optional/providers/services/lifecycle.py` (455)
- New `services/reconcile.py` ← `_sync_provider_mcp` (270), `reconcile_provider`
  (280), `reconcile_all_providers` (367), `reconcile_all` (410).
- **Keep** install/uninstall/repair + `_result`/`_probe_*`/`_descriptor`/
  `provider_cli_plan`/`_seed_provider_config`/`provision_all_provider_clis`.
- `reconcile.py` will import the install/probe helpers from `lifecycle.py`.
  `reconcile_provider`/`reconcile_all_providers`/`reconcile_all` are **public** →
  re-export them from `lifecycle.py` (`from .reconcile import ...`). Run
  `grep -rn "reconcile_provider\|reconcile_all" src tests` and confirm all
  importers still resolve. Likely cycle (lifecycle re-exports reconcile, reconcile
  imports lifecycle) → if so, lazy-import the helpers inside the reconcile
  functions.
- **Test:** `python -m pytest tests/ -q -k "reconcile or lifecycle or provision"`.

### C6 — `components/optional/agent_jobs/prompt_parser.py` (422)
- New `prompt_targets.py` ← `_parse_target` (78), `_infer_target_from_id` (110).
- New `prompt_aliases.py` ← `_split_tag_and_provider` (146),
  `_normalize_alias_map` (156), `_normalize_directives` (166),
  `_normalize_provider` (181).
- **Keep** `parse_prompt_launch_request` (199) + the timestamp/id/validate/bool/
  split-text/default helpers in `prompt_parser.py`; it imports the moved helpers
  from the two new modules.
- These are all private (underscore) and used only by `parse_prompt_launch_request`
  → no external re-export needed, just internal imports. Confirm with
  `grep -rn "_parse_target\|_split_tag_and_provider" src tests`.
- **Test:** `python -m pytest tests/ -q -k "prompt_parser or parse_prompt or prompt_launch"`.

---

## Explicitly OUT of scope (do not do — soft-400 policy, no seam)
- `lifecycle/components.py` (362), `coding_lsp/lsp_api.py` (315) — under 400, no
  mixed-concern win.
- Merging `item.py`+`rel.py` into a single `util.py` junk-drawer (B3 sends
  `ItemView` to `interfaces.py` deliberately).
- Splitting `mcp.py` into a new file (A2 is dedup-in-place only).

## Suggested order & batching
1. Item 0 (clean baseline).
2. A1, A2, A3 (dedup — independent, low risk).
3. B1–B4 (tiny files — independent).
4. C1–C6 (one commit each; heaviest churn, do last).

Each batch: ruff + targeted tests green → commit → ledger event.
