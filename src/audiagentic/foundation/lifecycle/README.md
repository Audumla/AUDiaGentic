# foundation/lifecycle/

## Purpose
Component-lifecycle capability: install, baseline sync, uninstall, and installed-state detection. Moved from `runtime/lifecycle` under doctrine v2 — lifecycle operates the component machinery that already lives in `foundation/components/`.

## Ownership
- Project layout creation (`.audiagentic/` directory structure)
- Baseline asset synchronization from template to project
- Installed-state detection and reporting
- Component marker files (read/write `.audiagentic/components/{id}.yaml`)
- Fresh installation bootstrapping
- Component-owned uninstall behavior
- Capability → provider-recipe reconciliation seam

## Must NOT Own
- Job execution or prompt launching (→ `components/agent_jobs`)
- Release audit generation (→ `release`)
- Harness orchestration — lifecycle publishes events; the harness reacts
  via event subscription, not direct imports

## Allowed Dependencies
- `foundation/*` — components machinery, contracts, config, events, capabilities
- `runtime/system` — read-only environment facts (sanctioned seam)

## Key Modules
| Module | Responsibility |
|--------|---------------|
| `baseline_sync.py` | Sync managed baseline assets from repo template to project |
| `components.py` | Install, uninstall, enable, disable components; read/write `.audiagentic/components/{id}.yaml` markers; publish lifecycle events |
| `detector.py` | Detect and report current installed state |
| `fresh_install.py` | Bootstrap a fresh project installation |
| `uninstall.py` | Remove runtime and component-owned files |
| `external_mcp_probe.py` | External MCP server probing |
| `observers.py` | Lifecycle event observers |

## Related Domains
- `release` — calls lifecycle after install to bootstrap release workflow
- `runtime/harness` — subscribes to `lifecycle.component.*` events to react to component changes
