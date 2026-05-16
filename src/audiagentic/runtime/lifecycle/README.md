# runtime/lifecycle/

## Purpose
Greenfield project lifecycle management: install, baseline sync, uninstall, and installed-state detection.

## Ownership
- Project layout creation (`.audiagentic/` directory structure)
- Baseline asset synchronization from template to project
- Installed-state detection and reporting
- Component marker files (read/write `.audiagentic/components/{id}.yaml`)
- Fresh installation bootstrapping
- Component-owned uninstall behavior

## Must NOT Own
- Job execution or prompt launching (→ `execution`)
- Durable job state (→ `runtime/state`)
- Release audit generation (→ `release`)
- Legacy upgrade paths

## Allowed Dependencies
- `foundation/contracts` — schema validation, error types
- `foundation/config` — project and provider config loading

## Key Modules
| Module | Responsibility |
|--------|---------------|
| `baseline_sync.py` | Sync managed baseline assets from repo template to project |
| `components.py` | Install, uninstall, enable, disable components; read/write `.audiagentic/components/{id}.yaml` markers |
| `detector.py` | Detect and report current installed state |
| `fresh_install.py` | Bootstrap a fresh project installation |
| `uninstall.py` | Remove runtime and component-owned files |

## Related Domains
- `release` — calls lifecycle after install to bootstrap release workflow
- `runtime/state` — sibling; state is separate from lifecycle
