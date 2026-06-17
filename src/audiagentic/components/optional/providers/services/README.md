# components/optional/providers/services/

Provider-agnostic service layer.

## Intent

Centralize behavior shared across all provider adapters so component APIs do not need provider-specific branches.

## Capabilities

- Load provider config and registry state.
- Build and persist provider model catalogs.
- Check provider health and installation status.
- Manage provider MCP entries.
- Reconcile configured providers against host state.
- Dispatch provider execution using descriptor metadata.

## Key Files

- `provider_registry.py` and `provider_config.py` load configured providers and descriptors.
- `catalog.py` and `provider_catalog.py` own model catalog refresh/persistence.
- `execution.py` routes runtime execution.
- `health.py`, `status.py`, and `lifecycle.py` compute install/runtime state and reconciliation plans.
- `managed_mcp_registry.py` and `mcp.py` manage provider MCP registration.
