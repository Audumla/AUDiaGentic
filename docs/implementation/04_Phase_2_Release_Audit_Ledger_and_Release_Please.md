# Phase 2 — Release / Audit / Ledger / Release Please

## Purpose

Deliver the release subsystem as a standalone core capability before any job engine is allowed to update tracked release docs indirectly.

## Scope

- runtime fragments for change events
- current tracked ledger sync
- deterministic current summary generation
- audit and check-in summaries
- release finalization checkpoints and resume logic
- baseline Release Please managed workflow/config
- legacy changelog/history conversion to ledger events

## Out of scope

- agent job orchestration
- provider execution
- Discord events

## Implementation order

1. PKT-RLS-001 — record fragment per change event
2. PKT-RLS-002 — sync current tracked ledger with lock and manifest
3. PKT-RLS-003 — regenerate current release markdown summary
4. PKT-RLS-004 — generate audit and check-in summaries
5. PKT-RLS-005 — finalize release with exactly-once historical append
6. PKT-RLS-006 — baseline Release Please workflow/config management
7. PKT-RLS-007 — convert legacy changelog/history to ledger events

## Exit gate

- tracked release docs can be generated with scripts only
- rerunning sync without new fragments is byte-identical
- finalize resume logic is tested against partial failure checkpoints
- legacy changelog conversion writes deterministic output and report
