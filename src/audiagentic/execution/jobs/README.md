# execution/jobs/

## Purpose
The active core of job orchestration. Contains all modules that drive a prompt request through the full agent job lifecycle.

## Ownership
- Prompt parsing and request normalization
- Job state machine transitions
- Packet execution and result collection
- Job control (cancel, stop, kill)
- Approval and review orchestration
- Release bridge (signals release domain on job completion)

## Must NOT Own
- Job record I/O (→ `runtime/state/jobs_store.py`)
- Session input I/O (→ `runtime/state/session_input_store.py`)
- Review bundle I/O (→ `runtime/state/reviews_store.py`)
- Provider-specific execution code (→ `interoperability/providers/adapters/`)

## Allowed Dependencies
- `foundation/contracts` — errors, schemas, canonical IDs
- `foundation/config` — provider config, project config
- `runtime/state` — jobs_store, session_input_store, reviews_store
- `interoperability/providers` — provider selection and dispatch
- `interoperability/protocols/streaming` — stream sink management

## Key Modules
| Module | Responsibility |
|--------|---------------|
| `prompt_launch.py` | Entry point: parse and launch a prompt request |
| `prompt_parser.py` | Normalize raw prompt text into a structured request |
| `state_machine.py` | Job state transitions and lifecycle enforcement |
| `packet_runner.py` | Execute a single job packet against a provider |
| `control.py` | Job control requests (cancel, stop, kill) |
| `approvals.py` | Approval workflow and review orchestration |
| `reviews.py` | Build and validate review reports and bundles |
| `records.py` | Job record construction (not persistence) |
| `profiles.py` | Workflow profile loading and application |
| `release_bridge.py` | Signal release domain on job completion |
| `prompt_trigger_bridge.py` | Bridge raw prompt trigger to prompt_launch |
