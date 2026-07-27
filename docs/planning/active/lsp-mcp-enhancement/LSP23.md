---
id: LSP23
order: 0
plan: lsp-mcp-enhancement
state: pending
created-by: agent
---

# Auto-install pre-commit hooks when languages are enabled via coding-lsp

## Description

When a language is auto-enabled by the coding-lsp component (via file open, lsp_add_language, or component enable), automatically install a pre-commit hook block for that language's lint/format commands — if the pre-commit-hooks-enabled flag is set. This keeps git commit linting seamless and implicit: users never call an explicit tool to manage hooks. The single toggle at the component level controls all behavior.

## Steps

1. Component config: add pre-commit-hooks-enabled boolean option to coding-lsp.yaml under options:. Defaults to true.

2. Language descriptor extension: add optional pre-commit-hooks: field to feature YAML files (coding-lsp/features/*.yaml). When present, defines shell commands for check and format phases. When absent, the language has no hook.

3. New module: `coding_lsp/git_hooks_sync.py` with single entry-point function `_sync_hook_for_language(project_root, language, install=True)`. Called whenever a language's enabled state changes. This function owns all logic — callers never touch flag checks, descriptor lookup, or managed-block machinery directly.

4. Managed-block integration (reusing source-control pattern): First install creates whole-owned file with managed block. Existing user hook gets block appended for coexistence. Remove language deletes only that language's block. Ownership tracked via ArtifactRegistry.

5. Integration points — four callers all call the same function:
   a) `coding_lsp_bootstrap.py` line 71: `_on_enabled` loops over configured languages, calls `_sync_hook_for_language(root, lang, install=True)`
   b) `lsp_session_resolution.py` line 193: `_resolve_language_servers_for_file` is called whenever any LSP tool (definition, references, hover, completion, etc.) operates on a file. Call chain: `lsp_api.definition(file, pos)` → `_positional_locations_op()` → `_open_file_session()` → `_resolve_language_servers_for_file()`. At line 225-229, this is where `set_feature_state` enables the language on auto-detect — hook install must happen immediately after that `set_feature_state` call.
   c) `lsp_config_api.py` line 402: `remove_language` calls `_sync_hook_for_language(root, language, install=False)`
   d) `coding_lsp_bootstrap.py` line 100: `_on_disabled` loops over enabled languages, calls `_sync_hook_for_language(root, lang, install=False)`

6. Component disable removes all hook blocks; if none remain deletes whole-owned file (check ArtifactRegistry proof).

Call chain detail for auto-detect:
  User runs: `definition("src/main.py", "10:5")`
    → `lsp_api.definition()` at `lsp_api.py`:78
      → `_positional_locations_op()` at `lsp_api.py`:65
        → `_open_file_session()` at `lsp_session_resolution.py`:273
          → `_resolve_language_servers_for_file()` at `lsp_session_resolution.py`:193
            → matches `.py` → `get_feature_state` at line 225
            → if not enabled → `set_feature_state` at line 227 → auto-enables python-ruff
            → `_auto_install_dependency` for ruff binary at line 234

## Files

- `src/audiagentic/config/components/coding-lsp.yaml` (add `options.pre-commit-hooks-enabled`)
- `src/audiagentic/config/components/coding-lsp/features/python-ruff.yaml` (add `pre-commit-hooks`)
- `src/audiagentic/components/coding_lsp/git_hooks_sync.py` (new — single entry point, ~150 lines)
- `src/audiagentic/components/coding_lsp/coding_lsp_bootstrap.py` (`_on_enabled` at line 71, `_on_disabled` at line 100)
- `src/audiagentic/components/coding_lsp/lsp_session_resolution.py` (`_resolve_language_servers_for_file` at line 193 — insert hook call after `set_feature_state` at line 227)
- `src/audiagentic/components/coding_lsp/lsp_config_api.py` (`remove_language` at line 402)

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

## Notes

The key design principle is a single entry point (`_sync_hook_for_language`) that owns all decision logic. Four callers (component enable/disable at `coding_lsp_bootstrap.py` lines 71/100, auto-detect on file open at `lsp_session_resolution.py` line 193, explicit remove at `lsp_config_api.py` line 402) call it — none of them need to know about flag checks, descriptor lookups, or managed-block mechanics. The auto-detect path is the most critical integration point: `_resolve_language_servers_for_file` runs on EVERY LSP tool invocation (definition, references, hover, completion, etc.) so the hook install must be fast and non-blocking.
