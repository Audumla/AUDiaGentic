---
id: LSP24
order: 0
plan: lsp-mcp-enhancement
state: completed
breadth: medium
skill: 2
work: S
---

# Generic LSP enablement via managed config blocks

## Description

Currently, opencode has special LSP enablement in its config with language-to-key mappings and aliases (e.g., `python` -> `pyright`, `cpp` -> `clangd`). The managed-config infrastructure is already in place:

- Provider descriptors declare `language_servers_config:` with `reader/writer/remover` pointing at adapter modules
- `ManagedConfigSpec` → `resolve_managed_config_path()` / `apply_managed_config_write()` / `apply_managed_config_remove()` wired through `language_server_family.py`
- `sync_language_servers_to_providers()` projects language bindings via the managed config framework

The remaining work is smaller than originally planned: extract only the opencode-specific hardcoded key mapping out of Python into YAML config. No new `lsp_enablement_config.py` module is needed — the existing architecture covers it.

## Steps

1. ~~Create a generic LSP enablement config system in the coding-lsp component~~ — **NOT NEEDED**: provider descriptors + ManagedConfigSpec already provide this (see RV849)

2. ~~Update the managed-config framework to support LSP enablement blocks~~ — **NOT NEEDED**: `apply_managed_config_write()`, `apply_managed_config_remove()`, `sync_managed_config()` all already handle LSP entries via `ManagedConfigSpec` (see RV849)

3. Extract hardcoded language-to-key mapping from `opencode/language_servers.py` into YAML config:
   a) Add `lsp-key-mapping:` field to `config/providers/opencode.yaml` provider descriptor with the current `_LANGUAGE_TO_OPENCODE_KEY` mappings:
      ```yaml
      lsp-key-mapping:
        python: pyright
        cpp: clangd
        markdown: marksman
        python-ruff: ruff
        rust: rust
        typescript: typescript
        yaml: yaml-ls
      ```
   b) Update `adapters/opencode/language_servers.py` to read the mapping from a new `_load_key_mapping()` function loaded from the provider descriptor, replacing the hardcoded `_LANGUAGE_TO_OPENCODE_KEY` dict (line 27)
   c) Remove `_OPENCODE_KEY_TO_LANGUAGE` reverse map — compute it at load time from the same YAML source

4. ~~Update `codex/language_servers.py`~~ — **NOT NEEDED**: codex uses language IDs directly, no key mapping required

5. ~~Update other harness adapters (pi, claude, cline, copilot, gemini, qwen, roo)~~ — **NOT NEEDED**: only 3 adapters have LSP support (opencode, codex, qwen); pi and others self-provide LSP and are skipped by `providers_api.py:533` when `descriptor.language_servers_config is None`

## Detailed Solution & Technical Design

### Architecture Improvements

1. **Centralized Config in LSP Component**: ~~Keep the LSP-to-harness config in the coding-lsp component~~ — **Already done**: provider descriptors (`config/providers/*.yaml`) declare `language_servers_config:` with reader/writer/remover, and feature YAMLs (`coding-lsp/features/*.yaml`) define language specs

2. **Generic to Blocks/Managed Config Items**: ~~Make the LSP config more generic to blocks~~ — **Already done**: `ManagedConfigSpec` + `apply_managed_config_write()` / `apply_managed_config_remove()` handle LSP entries generically through `language_server_family.py`

3. **Simplified LSP Code & Config**: Extract remaining hardcoded mapping from opencode adapter into YAML

### Key Components (revised)

- ~~`src/audiagentic/components/coding_lsp/lsp_enablement_config.py`~~ — NOT NEEDED; existing architecture covers this
- `src/audiagentic/config/providers/opencode.yaml` — add `lsp-key-mapping:` field with current hardcoded mappings
- `src/audiagentic/components/providers/adapters/opencode/language_servers.py` — replace hardcoded `_LANGUAGE_TO_OPENCODE_KEY` dict (line 27) with YAML-sourced mapping loaded via new `_load_key_mapping()` function

## Code Samples & Guidance

### Revised: YAML key mapping in provider descriptor

```yaml
# config/providers/opencode.yaml (add after language_servers_config block)
language_servers_config:
  config_path: ".opencode/opencode.json"
  reader: "audiagentic.components.providers.adapters.opencode.language_servers:read_language_servers_opencode"
  writer: "audiagentic.components.providers.adapters.opencode.language_servers:write_language_servers_opencode"
  remover: "audiagentic.components.providers.adapters.opencode.language_servers:remove_language_servers_opencode"
  format: "opencode-json"
  key-mapping:
    python: pyright
    cpp: clangd
    markdown: marksman
    python-ruff: ruff
    rust: rust
    typescript: typescript
    yaml: yaml-ls
```

### Revised: Load mapping from descriptor

```python
# adapters/opencode/language_servers.py — replace lines 27-40
def _load_key_mapping() -> dict[str, str]:
    """Load language→opencode key mapping from provider descriptor."""
    from audiagentic.components.providers.descriptors.registry import get_descriptor
    
    descriptor = get_descriptor("opencode")
    if descriptor and descriptor.language_servers_config:
        raw = descriptor.language_servers_config.raw or {}
        mapping_raw = raw.get("key-mapping", {})
        return dict(mapping_raw) if isinstance(mapping_raw, dict) else {}
    # Fallback to defaults
    return {
        "python": "pyright",
        "cpp": "clangd",
        "markdown": "marksman",
        "python-ruff": "ruff",
        "yaml": "yaml-ls",
    }

_LANGUAGE_TO_OPENCODE_KEY: dict[str, str] = _load_key_mapping()
_OPENCODE_KEY_TO_LANGUAGE: dict[str, str] = {v: k for k, v in _LANGUAGE_TO_OPENCODE_KEY.items()}
```

### NOT NEEDED (crossed out from original plan)

~~`LspEnablementMapping` dataclass and `LspEnablementConfig` class — existing `ManagedConfigSpec` + feature YAMLs already provide centralized config-driven LSP enablement.~~

~~`create_lsp_enablement_fragment()` — existing `apply_managed_config_write()` handles LSP entries generically.~~

## Files

- ~~`src/audiagentic/components/coding_lsp/lsp_enablement_config.py` (new generic LSP enablement config system)~~ — NOT NEEDED
- ~~`src/audiagentic/foundation/toolchains/managed_config.py` (extend to support LSP enablement blocks)~~ — NOT NEEDED, already supports LSP
- `src/audiagentic/config/providers/opencode.yaml` (add `lsp-key-mapping:` under `language_servers_config:`)
- `src/audiagentic/components/providers/adapters/opencode/language_servers.py` (replace hardcoded `_LANGUAGE_TO_OPENCODE_KEY` dict with YAML-sourced mapping via `_load_key_mapping()`)
- ~~`src/audiagentic/components/providers/adapters/codex/language_servers.py` (update to use managed-block pattern)~~ — NOT NEEDED, already uses language IDs directly
- ~~Other harness adapters as needed (pi, claude, cline, copilot, gemini, qwen, roo)~~ — NOT NEEDED, only 3 adapters have LSP support

## Validation

- ~~All harnesses use the same recipe-based config for LSP enablement mappings~~ — Already true via ManagedConfigSpec
- ~~Language-to-key mappings are configurable and not hardcoded in adapters~~ — Partially: codex/qwen already use IDs directly; opencode still has hardcoded mapping (this item)
- ~~All harnesses respect the `pre-commit-hooks-enabled` component flag~~ — Covered by LSP23, not this item
- ~~All harnesses use the same `lsp_add_language` / `lsp_remove_language` APIs~~ — Already true via lsp_config_api
- ~~Pre-commit hooks are managed consistently across all harnesses using the managed-block pattern~~ — Covered by LSP23

### Revised validation for actual remaining work:
- `_LANGUAGE_TO_OPENCODE_KEY` dict loaded from opencode provider descriptor YAML instead of hardcoded Python
- Adding a new language to `coding-lsp/features/` with an opencode-specific key requires only YAML config, no Python changes
- Reversing the mapping (`_OPENCODE_KEY_TO_LANGUAGE`) computed at load time from same source
- No regressions in existing opencode LSP sync/prune flows

## Effort & Risk

**Revised (reduced):** Small complexity — 2 files changed. One YAML config addition, one Python function to load the mapping from descriptor.

Low risk: mapping is additive and backward-compatible; fallback defaults preserve current behavior if YAML field is missing.

## Standards

- managed-config-pattern — Use the existing ManagedConfigSpec framework for LSP enablement blocks
- lsp-component-consistency — Keep LSP configuration in the coding-lsp component and provider descriptors

## Notes

The key design principle is a single source of truth for LSP enablement mappings that all harnesses can use. This ensures consistency across opencode, codex, pi, and other harnesses while allowing harness-specific server names and aliases to be configured centrally.

### Revised scope (RV849)
The original plan proposed a new `lsp_enablement_config.py` module with `LspEnablementMapping` dataclass and updates to 7+ harness adapters. The existing managed-config infrastructure already covers the architecture vision:

- Provider descriptors declare `language_servers_config:` with reader/writer/remover (opencode, codex, qwen all have this)
- `ManagedConfigSpec` → `resolve_managed_config_path()` / `apply_managed_config_write()` / `apply_managed_config_remove()` wired through `language_server_family.py`
- `sync_language_servers_to_providers()` projects language bindings via the managed config framework

Only 3 adapters (opencode, codex, qwen) have LSP support — pi, claude, cline, etc. self-provide LSP and are skipped by `providers_api.py:533` when `descriptor.language_servers_config is None`.

Remaining work is just extracting opencode's hardcoded `_LANGUAGE_TO_OPENCODE_KEY` mapping from Python into YAML config.

## Change Log

- 2026-07-28T00:49:21.076892+00:00 (updated-by): Updated: section:description, section:steps, section:detailed_solution, section:code_samples, section:files, section:validation, section:effort_risk, section:standards, section:notes, work='S'
- 2026-07-28T00:51:25.127825+00:00 (state-transition): State: pending → in_progress
- 2026-07-28T01:05:16.208184+00:00 (state-transition): State: in_progress → completed
- 2026-07-28T01:05:35.025785+00:00 (updated-by): Updated (no visible changes)
- 2026-07-28T01:12:28.803721+00:00 (state-transition): State: completed → in_progress
- 2026-07-28T01:26:01.601811+00:00 (state-transition): State: in_progress → completed
