# components/optional/providers/adapters/

Provider-specific runtime adapters.

## Intent

Each adapter package translates AUDiaGentic job execution into one external provider's CLI or runtime contract.

## Shared Pattern

Most provider folders contain:

- `adapter.py` execution bridge for commands, streaming, and result normalization.
- `descriptor.py` static metadata: install recipe, capabilities, MCP shape, access mode.
- `surface.py` managed prompt-surface content for agent instruction files.

Some providers add extra helpers such as `hooks.py`, `mcp_format.py`, or `language_servers.py` when their integration shape needs extra translation.

## How To Use This Area

Use this directory when behavior differs by provider. Use `services/` for provider-agnostic orchestration and catalog management.
