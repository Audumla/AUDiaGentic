# runtime/lifecycle/

## Purpose
Project lifecycle management — everything that happens when AUDiaGentic is installed into, updated in, or queried about a project.

## Ownership
- Project layout creation (`.audiagentic/` directory structure)
- Baseline asset synchronization from template to project
- Installed-state detection and reporting
- Component manifest (read/write `installed.json`)
- Fresh installation bootstrapping

## Must NOT Own
- Job execution or prompt launching (→ `execution`)
- Durable job state (→ `runtime/state`)
- Release audit generation (→ `release`)

## Allowed Dependencies
- `foundation/contracts` — schema validation, error types
- `foundation/config` — project and provider config loading

## Key Modules
| Module | Responsibility |
|--------|---------------|
| `baseline_sync.py` | Sync managed baseline assets from repo template to project |
| `detector.py` | Detect and report current installed state |
| `fresh_install.py` | Bootstrap a fresh project installation |
| `manifest.py` | Build, read, and write the component manifest (`installed.json`) |

## Related Domains
- `release` — calls lifecycle after install to bootstrap release workflow
- `runtime/state` — sibling; state is separate from lifecycle
