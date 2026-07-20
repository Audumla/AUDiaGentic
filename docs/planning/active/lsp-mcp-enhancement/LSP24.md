---
id: LSP24
order: 0
plan: plan-lsp-mcp-enhancement
state: not_done
breadth: medium
skill: standard
---

# Generic LSP enablement via managed config blocks

## Description

Currently, opencode has special LSP enablement in its config with language-to-key mappings and aliases (e.g., `python` -> `pyright`, `cpp` -> `clangd`). Instead of having these mappings in each harness adapter, we should:

1. Keep the LSP-to-harness config in the LSP component (just like we do for hindsight)
2. Make the LSP config more generic to blocks/managed config items as is already done for other managed config items
3. Simplify LSP code and config across all harnesses by using the managed-block pattern

## Steps

1. Create a generic LSP enablement config system in the coding-lsp component that maps language IDs to harness-specific server names and aliases
2. Update the managed-config framework to support LSP enablement blocks (similar to how it supports other managed config items)
3. Remove hardcoded language-to-key mappings from `opencode/language_servers.py` and use the generic config system
4. Update `codex/language_servers.py` and other harness adapters to use the generic managed-block pattern for LSP configuration
5. Ensure all harnesses follow the same rules for when languages are enabled or not:
   - Respect the `pre-commit-hooks-enabled` component flag
   - Use the same `lsp_add_language` / `lsp_remove_language` APIs
   - Follow the managed-block pattern for pre-commit hook management and LSP enablement

## Detailed Solution & Technical Design

### Architecture Improvements

1. **Centralized Config in LSP Component**: Keep the LSP-to-harness config in the coding-lsp component (like we do for hindsight)
2. **Generic to Blocks/Managed Config Items**: Make the LSP config more generic to blocks as is already done for other managed config items using the existing `managed_config.py` framework
3. **Simplified LSP Code & Config**: Remove hardcoded language-to-key mappings from individual harness adapters and use the generic managed-block pattern

### Key Components

- `src/audiagentic/components/coding_lsp/lsp_enablement_config.py` - New generic LSP enablement config system with default mappings for common languages
- `src/audiagentic/foundation/toolchains/managed_config.py` - Extend to support LSP enablement blocks
- `src/audiagentic/components/providers/adapters/opencode/language_servers.py` - Update to use managed-block pattern
- `src/audiagentic/components/providers/adapters/codex/language_servers.py` - Update to use managed-block pattern

## Code Samples & Guidance

### LspEnablementConfig Example

```python
@dataclass(frozen=True)
class LspEnablementMapping:
    """Mapping for a language to harness-specific server names and aliases."""
    language_id: str
    server_names: list[str]
    aliases: list[str] = field(default_factory=list)

class LspEnablementConfig:
    """Generic LSP enablement configuration system."""
    
    _DEFAULT_MAPPINGS: dict[str, LspEnablementMapping] = {
        "python": LspEnablementMapping(
            language_id="python",
            server_names=["pyright", "pyright-langserver"],
            aliases=["python", "pyright"],
        ),
        "cpp": LspEnablementMapping(
            language_id="cpp",
            server_names=["clangd"],
            aliases=["cpp", "clangd"],
        ),
        # ... other languages
    }
```

### Managed Config Fragment Example

```python
def create_lsp_enablement_fragment(language_id: str, server_names: list[str], file_extensions: list[str]) -> ManagedConfigFragment:
    """Create a managed config fragment for LSP enablement."""
    return ManagedConfigFragment(
        fragment_type="lsp-enablement",
        language_id=language_id,
        data={
            "server_names": server_names,
            "file_extensions": file_extensions,
        }
    )
```

## Files

- `src/audiagentic/components/coding_lsp/lsp_enablement_config.py` (new generic LSP enablement config system)
- `src/audiagentic/foundation/toolchains/managed_config.py` (extend to support LSP enablement blocks)
- `src/audiagentic/components/providers/adapters/opencode/language_servers.py` (update to use managed-block pattern)
- `src/audiagentic/components/providers/adapters/codex/language_servers.py` (update to use managed-block pattern)
- Other harness adapters as needed (pi, claude, cline, copilot, gemini, qwen, roo)

## Validation

- All harnesses use the same recipe-based config for LSP enablement mappings
- Language-to-key mappings are configurable and not hardcoded in adapters
- All harnesses respect the `pre-commit-hooks-enabled` component flag
- All harnesses use the same `lsp_add_language` / `lsp_remove_language` APIs
- Pre-commit hooks are managed consistently across all harnesses using the managed-block pattern

## Effort & Risk

Mid complexity - requires creating a recipe-based configuration system and updating multiple harness adapters.

Low risk - recipe-based config is additive and doesn't break existing functionality; mappings can be tested independently.

## Standards

- managed-config-pattern — Use the existing managed-config framework for LSP enablement blocks
- lsp-component-consistency — Keep LSP configuration in the coding-lsp component

## Notes

The key design principle is a single source of truth for LSP enablement mappings that all harnesses can use. This ensures consistency across opencode, codex, pi, and other harnesses while allowing harness-specific server names and aliases to be configured centrally.
