# channels/cli/

## Purpose
Command-line interface channel. The canonical operator entry point for all AUDiaGentic commands.

## Ownership
- CLI argument parsing and subcommand dispatch (`main.py`)
- Surface-level input normalization for each command
- JSON output formatting for all command results

## Must NOT Own
- Business logic beyond argument parsing and dispatch
- Persistent state (→ `runtime/state`)
- Provider knowledge (→ `interoperability/providers`)

## Allowed Dependencies
- `foundation/contracts` — error types
- `foundation/config` — project config loading
- `runtime/state` — read job records for job-control and session-input
- `execution/jobs` — prompt_launch, control, prompt_trigger_bridge, prompt_parser
- `release` — bootstrap_release_workflow
- `tools/misc/*` — lifecycle_stub, provider_status, refresh_model_catalog bridges

## Available Commands
| Command | Delegate |
|---------|----------|
| `prompt-launch` | `execution.jobs.prompt_launch` |
| `prompt-trigger-bridge` | `execution.jobs.prompt_trigger_bridge` |
| `job-control` | `execution.jobs.control` |
| `session-input` | `runtime.state.session_input_store` |
| `release-bootstrap` | `release.bootstrap` |
| `providers-status` | `tools/misc/provider_status.py` |
| `lifecycle-stub` | `tools/misc/lifecycle_stub.py` |
| `refresh-model-catalog` | `tools/misc/refresh_model_catalog.py` |

## Entry Point
```bash
python -m audiagentic.channels.cli.main <command> [args]
# or via installed script:
audiagentic <command> [args]
```
