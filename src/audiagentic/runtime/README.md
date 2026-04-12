# runtime/

## Purpose
Runtime infrastructure domain. Owns two distinct responsibilities:
1. **Lifecycle** — project installation, baseline sync, manifest management
2. **State** — durable persistence of live job records, session input, and review bundles

## Ownership
- Project lifecycle operations (install, update, detect state)
- Baseline asset synchronization from template to project
- Component manifest read/write
- Durable job record persistence
- Durable session input persistence
- Durable review bundle persistence

## Must NOT Own
- Job orchestration logic (→ `execution`)
- Provider dispatch (→ `interoperability`)
- Release audit generation (→ `release`)
- Channel formatting (→ `channels`)

## Allowed Dependencies
- `foundation/contracts` — canonical errors, schema validation, canonical IDs
- `foundation/config` — project configuration

## Subdomains

### lifecycle/
Manages the installed state of AUDiaGentic in a project:
- `baseline_sync.py` — synchronize managed baseline from template
- `fresh_install.py` — first-time installation
- `detector.py` — detect current installed state
- `manifest.py` — read/write component manifest

### state/
Durable persistence layer extracted from `execution/jobs/`:
- `jobs_store.py` — job record read/write
- `session_input_store.py` — session input event persistence
- `reviews_store.py` — review bundle and report persistence

## Dependency Note
`runtime` must NOT import from `channels` or `execution`. It is a lower-level layer that both of those domains depend on.
