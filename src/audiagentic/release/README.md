# release/

Release management, audit, and change tracking for the system.

## Purpose

Governs the release lifecycle:
- Release ledger and fragment management
- Change event recording
- Audit and checkin report generation
- Release finalization
- Version bootstrapping

## Owns

- Release ledger (NDJSON format)
- Change event fragments
- Audit and release summary generation
- Release bootstrap and lifecycle
- History import from legacy formats

## Key modules

- **fragments.py**: Change event recording
- **finalize.py**: Release finalization
- **sync.py**: Ledger merge and sync
- **audit.py**: Audit and checkin report generation
- **current_summary.py**: Release summary generation
- **bootstrap.py**: Release workflow initialization

## Boundary with execution/jobs/

`execution/jobs/release_bridge.py` publishes job completion events to the release ledger via `record_change_event()`. This is a one-way bridge (execution → release).

## Must not own

- Job orchestration
- Provider execution
- Runtime lifecycle (install, update, uninstall)

## Migration notes

- Moved from `runtime/release/` to top-level `release/` (Slice F, 2026-04-12)
- Now a first-class domain, not a runtime subdomain
