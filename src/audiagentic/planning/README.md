# planning/

## Purpose
Planning workflows and task management for AUDiaGentic. Owns the full lifecycle of planning items: requests, specifications, plans, tasks, work packages, and standards.

## Ownership
- Planning item creation, update, mutation, and deletion
- Item state tracking (pending, in-progress, complete, archived)
- Planning profiles and workflow configuration
- MCP tool surface for planning operations
- Planning data persistence under `.audiagentic/planning/`

## Must NOT Own
- Job execution orchestration (→ `execution`)
- Provider selection or dispatch (→ `interoperability`)
- Release audit or change ledger (→ `release`)
- Runtime state or job records (→ `runtime/state`)

## Allowed Dependencies
- `foundation/contracts` — schema validation and canonical error types
- `foundation/config` — project configuration loading

## Code That Belongs Here
- Planning API and domain model (`app/`, `domain/`, `fs/`)
- MCP server for planning tool surface
- Profile configuration and workflow overlays
- TM helper utilities (`tools/planning/tm_helper.py` bridges here)

## Code That Does NOT Belong Here
- Anything that launches or executes an agent job
- Streaming or provider communication
- Release bootstrap or audit generation

## Related Domains
- `execution` — jobs reference planning items by ID
- `release` — completed items feed the change ledger
- `foundation` — shared contracts and validation
