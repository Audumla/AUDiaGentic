# execution/

## Purpose
Job orchestration and execution domain. Owns the end-to-end lifecycle of a prompt request from receipt through agent job completion.

## Ownership
- Prompt launch and request parsing
- Job state machines and lifecycle control
- Packet execution and approval workflows
- Prompt trigger bridge and inter-job control
- Release bridge (thin connector from execution to release)

## Must NOT Own
- Durable state persistence for job records or session input (→ `runtime/state`)
- Provider selection or dispatch logic (→ `interoperability/providers`)
- Streaming protocol or sink management (→ `interoperability/protocols/streaming`)
- Release audit generation or ledger management (→ `release`)
- Channel formatting or rendering logic (→ `channels`)

## Allowed Dependencies
- `foundation/contracts` — canonical errors and schema validation
- `foundation/config` — provider and project config
- `runtime/state` — read/write job records, session input
- `interoperability/providers` — provider dispatch and selection
- `interoperability/protocols/streaming` — stream sink construction

## Code That Belongs Here
- `jobs/prompt_launch.py` — launch a prompt request as a job
- `jobs/state_machine.py` — job state transitions
- `jobs/control.py` — pause, cancel, kill
- `jobs/packet_runner.py` — execute a job packet
- `jobs/approvals.py` — approval workflow
- `jobs/release_bridge.py` — thin bridge to release domain

## Code That Does NOT Belong Here
- Job record read/write (→ `runtime/state/jobs_store.py`)
- Provider adapter code (→ `interoperability/providers/adapters/`)
- CLI argument parsing (→ `channels/cli/`)

## Related Domains
- `runtime/state` — consumes durable persistence
- `interoperability` — delegates provider and streaming work
- `channels` — receives prompt requests from operator surfaces
- `release` — notified when jobs complete for audit trail
