---
id: LSP23
order: 0
plan: lsp-mcp-enhancement
state: completed
created-by: agent
---

# Auto-install pre-commit hooks when languages are enabled via coding-lsp

## Description

When a language is auto-enabled by the coding-lsp component (via file open, lsp_add_language, or component enable), automatically install a pre-commit hook block for that language's lint/format commands — if the pre-commit-hooks-enabled flag is set. This keeps git commit linting seamless and implicit: users never call an explicit tool to manage hooks. The single toggle at the component level controls all behavior.

## Steps

1. Component config: add pre-commit-hooks-enabled boolean option to coding-lsp.yaml under options:. Defaults to true.
   **STATUS: ✅ Done — present at `options.pre-commit-hooks-enabled` in coding-lsp.yaml**

2. Language descriptor extension: add optional pre-commit-hooks: field to feature YAML files (coding-lsp/features/*.yaml). When present, defines shell commands for check and format phases. When absent, the language has no hook.
   **STATUS: ✅ Done — python.yaml and python-ruff.yaml both declare `pre-commit-hooks`; parsed into `LanguageSpec.pre_commit_hooks` via `language_spec_from_data()`**

3. New module: `coding_lsp/git_hooks_sync.py` with single entry-point function `_sync_hook_for_language(project_root, language_id, install=True)`. Called whenever a language's enabled state changes. This function owns all logic — callers never touch flag checks, descriptor lookup, or managed-block machinery directly.
   **STATUS: ✅ Done — module exists at ~240 lines; uses `apply_managed_block`, `remove_managed_block`, `ArtifactRegistry`**

4. Managed-block integration (reusing source-control pattern): First install creates whole-owned file with managed block. Existing user hook gets block appended for coexistence. Remove language deletes only that language's block. Ownership tracked via ArtifactRegistry.
   **STATUS: ✅ Done — implemented in `git_hooks_sync.py`**

5. Integration points — four callers all call the same function:
   a) `coding_lsp_bootstrap.py` `_on_enabled`: loops over configured languages, calls `_sync_hook_for_language(root, lang, install=True)`
      **STATUS: ✅ Done — lines 103-109**
   b) `lsp_session_resolution.py` `_resolve_language_servers_for_file`: called whenever any LSP tool operates on a file; at the auto-detect path (after `set_feature_state` enables a new language), call `_sync_hook_for_language`
      **STATUS: ✅ Done — lines 241-254**
   c) `lsp_config_api.py` `remove_language`: calls `_sync_hook_for_language(root, language, install=False)`
      **STATUS: ❌ NOT WIRED — fix required (see RV848)**
   d) `coding_lsp_bootstrap.py` `_on_disabled`: loops over enabled languages, calls `_sync_hook_for_language(root, lang, install=False)`
      **STATUS: ✅ Done — lines 146-149**

6. Component disable removes all hook blocks; if none remain deletes whole-owned file (check ArtifactRegistry proof).
   **STATUS: ✅ Done via `_on_disabled` handler above**

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files

- `src/audiagentic/config/components/coding-lsp.yaml` (add `options.pre-commit-hooks-enabled`) — ✅ done
- `src/audiagentic/config/components/coding-lsp/features/python-ruff.yaml` (add `pre-commit-hooks`) — ✅ done
- `src/audiagentic/config/components/coding-lsp/features/python.yaml` (add `pre-commit-hooks`) — ✅ done
- `src/audiagentic/components/coding_lsp/git_hooks_sync.py` (new — single entry point, ~240 lines) — ✅ done, 2 fixes needed (RV848)
- `src/audiagentic/components/coding_lsp/coding_lsp_bootstrap.py` (`_on_enabled` at line 72, `_on_disabled` at line 123) — ✅ wired
- `src/audiagentic/components/coding_lsp/lsp_session_resolution.py` (`_resolve_language_servers_for_file` at line 182 — insert hook call after `set_feature_state` at line 227) — ✅ wired
- `src/audiagentic/components/coding_lsp/lsp_config_api.py` (`remove_language` at line 402) — ❌ NOT WIRED, needs fix (RV848)

## Validation

- Enable coding-lsp component → `.git/hooks/pre-commit` exists with ruff block.
- Open a `.py` file in the project → ruff hook appears even if component was already enabled (auto-detect path through `_resolve_language_servers_for_file`).
- `lsp_add_language("yaml")` → no hook block added (yaml has no pre-commit-hooks declared).
- `lsp_remove_language("python-ruff")` → python-ruff block removed, other blocks and user content preserved.
- Set `pre-commit-hooks-enabled: false` → all blocks removed on next disable; new enables skip installation.
- User's own pre-commit script → block appended, never overwritten.

## Effort & Risk

Mid complexity — new module (~150 lines), three existing files modified, one config file extended.

Low risk: hooks are opt-in (component flag defaults true), managed-blocks safe with user content preserved, graceful skip when .git/hooks absent or no hook spec declared.

## Standards



## Notes

The key design principle is a single entry point (`_sync_hook_for_language`) that owns all decision logic. Four callers (component enable/disable at `coding_lsp_bootstrap.py`, auto-detect on file open at `lsp_session_resolution.py`, explicit remove at `lsp_config_api.py`) call it — none of them need to know about flag checks, descriptor lookups, or managed-block mechanics.

### Known gaps (RV848)

**Gap 1: `remove_language` does not call `_sync_hook_for_language`**
- File: `lsp_config_api.py`, function `remove_language()` at line 402
- Current behavior: disables feature, regenerates cache, shuts down sessions, prunes provider configs — but pre-commit hook block for that language stays installed
- Fix: insert after line 416 (before `prune_language_servers_from_providers`):
```python
from .git_hooks_sync import _sync_hook_for_language
_sync_hook_for_language(project_root, language, install=False)
```

**Gap 2: Closing managed-block marker uses literal string instead of f-string**
- File: `git_hooks_sync.py`, function `_hook_body_for_language()` at line 58
- Current code:
```python
lines.append("# <<< audiagentic:_HOOK_BLOCK_ID:language-hooks <<<")
```
- Fix (line 58):
```python
lines.append(f"# <<< audiagentic:{_HOOK_BLOCK_ID}:language-hooks <<<")
```
- Also broken on line 203 in `_remove_hook_block` fallback — same literal string pattern needs f-string interpolation

## Change Log

- 2026-07-28T00:48:25.246969+00:00 (updated-by): Updated: section:steps, section:notes, section:files
- 2026-07-28T00:51:25.118290+00:00 (state-transition): State: pending → in_progress
- 2026-07-28T01:05:16.198348+00:00 (state-transition): State: in_progress → completed
- 2026-07-28T01:05:35.024541+00:00 (updated-by): Updated (no visible changes)
- 2026-07-28T01:12:28.785043+00:00 (state-transition): State: completed → in_progress
- 2026-07-28T01:26:01.592191+00:00 (state-transition): State: in_progress → completed
