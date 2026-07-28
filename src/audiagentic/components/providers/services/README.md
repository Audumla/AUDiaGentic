# components/providers/services/

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

## Layout

```
services/
├── __init__.py
├── secrets.py                          # cross-cutting (5+ groups depend)
├── reconcile.py                        # central orchestrator
│
├── config/                             # provider configuration & features
│   ├── provider_config.py
│   ├── provider_catalog.py
│   ├── model_source_config.py
│   └── feature_resolution.py
│
├── catalog/                            # model catalogs & projections
│   ├── catalog.py
│   ├── source_catalog.py
│   └── models.py
│
├── execution/                          # runtime execution & prompt ops
│   ├── execution.py
│   ├── public_execution.py
│   ├── launch_env.py
│   ├── public_prompt_operations.py
│   └── prompt_syntax.py
│
├── lifecycle/                          # install, health, status
│   ├── lifecycle.py
│   ├── health.py
│   ├── status.py
│   └── public_materialize.py
│
├── capabilities/                       # provider capability families & handlers
│   ├── automation_registry.py
│   ├── cli_lifecycle_handler.py
│   ├── cli_lifecycle_family.py
│   ├── generated_surface_family.py
│   ├── managed_mcp_family.py
│   ├── model_projection_family.py
│   ├── model_projection_handler.py
│   ├── managed_hooks_family.py
│   ├── self_provided_lsp_family.py
│   ├── self_provided_lsp_handler.py
│   ├── language_server_family.py
│   ├── recipe_definitions.py
│   ├── recipe_steps.py
│   ├── declarative_recipe_handler.py
│   └── plugin_entries.py
│
├── mcp/                                # MCP server management
│   ├── mcp.py
│   ├── mcp_projection.py
│   ├── mcp_sync.py
│   └── managed_mcp_registry.py
│
├── session/                            # session surface resolution
│   ├── session_surface_resolution.py
│   ├── harness_observability_inventory.py
│   └── harness_status_observer_resolution.py
│
└── host/                               # host adapter & probe
    ├── host_adapter.py
    ├── host_capabilities.py
    └── system_probe.py
```

## Key Files

- `config/provider_config.py` loads configured providers and descriptors.
- `catalog/catalog.py` and `config/provider_catalog.py` own model catalog refresh/persistence.
- `execution/execution.py` routes runtime execution.
- `lifecycle/health.py`, `lifecycle/status.py`, and `lifecycle/lifecycle.py` compute install/runtime state and reconciliation plans.
- `mcp/managed_mcp_registry.py` and `mcp/mcp.py` manage provider MCP registration.
