# runtime/rig/

Embedded and external model-backend management.

## Intent

Provide one place for model rig discovery, launch, HTTP probing, and persisted rig state.

## Capabilities

- Store and load rig model profiles.
- Query rig HTTP endpoints for version/model info.
- Reuse or launch embedded rig processes.
- Track rig process registry/state.

## Subareas

- `embedded/` launch/config/process helpers for bundled llama-server style backends.
- top-level modules cover HTTP probing, registry state, and shared rig models.
