# components/ledger/

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
- `contracts/`: Change event, lifecycle plan, and lifecycle result JSON Schema definitions

## Key modules

- **fragments.py**: Change event recording
- **sync.py**: Ledger merge and sync
- **audit.py**: Audit and checkin report generation
- **current_summary.py**: Release summary generation
- **ledger_bootstrap.py**: Release workflow initialization
- **ledger_mcp.py**: MCP tool interface for ledger operations
- **ledger_manage_mcp.py**: MCP management tools for ledger
- **ledger_api.py**: Ledger API surface
- **archive.py**: Ledger history archiving

## Release boundary

`archive_for_release(project_root, release_id)` is the only release archival
boundary. It synchronizes pending fragments, stamps the selected current
events, and returns their immutable event IDs for release rendering. A retry
for an already archived release is read-only and cannot claim events that
arrived for the next release. Conflicting historical event IDs and malformed
persisted records fail closed with typed ledger errors.

Source-control commit stamping is deliberately disabled by default. Release
finalization must never stamp its own generated commit back into the ledger;
otherwise archive output changes after the commit and creates a feedback loop.

## Must not own

- Job orchestration
- Provider execution
- Runtime lifecycle (install, update, uninstall)

## Migration notes

- Moved from `runtime/release/` to top-level `release/` (Slice F, 2026-04-12)
- Now a first-class domain, not a runtime subdomain
