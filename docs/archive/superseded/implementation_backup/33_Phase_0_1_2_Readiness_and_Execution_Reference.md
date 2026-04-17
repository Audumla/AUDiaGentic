# Phase 0–2 Readiness and Execution Reference

This document is the execution reference for the first three implementation stages and their additive extension lanes:
- Phase 0 / 0.1 / 0.2 — Contracts and scaffolding plus incremental extensions
- Phase 1 / 1.1 / 1.2 — Lifecycle and project enablement plus incremental extensions
- Phase 2 / 2.1 / 2.2 — Release, audit, ledger, Release Please baseline, plus incremental extensions

Its purpose is to give any worker a fast but authoritative picture of:
- what is ready to implement
- what order packets must follow
- where the parallel execution windows are
- what must be true before the next phase opens

---

## Readiness summary

### Phase 0
Ready to implement immediately.

Required outputs:
- canonical ids and naming validator
- schema package and schema validator
- ownership matrix and glossary
- example project scaffold
- lifecycle CLI stub and checkpoint emitter
- shared error envelope and code registry
- CI validators and packet dependency validation

### Phase 1
Ready to implement once Phase 0 exit gate is closed.

Required outputs:
- installed-state detector
- lifecycle manifest and checkpoint writer
- fresh install apply and validate
- update dispatcher and version module selection
- legacy cutover
- uninstall current AUDiaGentic
- document migration outcomes and reports

### Phase 2
Ready to implement once Phase 1 exit gate is closed.

Required outputs:
- fragment recording
- locked ledger sync + manifest
- current release summary regeneration
- audit and check-in summaries
- release finalization with exactly-once append
- Release Please baseline workflow/config management
- legacy changelog/history conversion
- full end-to-end release integration tests

---

## Strict execution order

### Phase 0 topological order

Tier 0:
- PKT-FND-001

Tier 1:
- PKT-FND-002
- PKT-FND-003

Tier 2:
- PKT-FND-004
- PKT-FND-006

Tier 3:
- PKT-FND-005

Tier 4:
- PKT-FND-007

### Phase 1 topological order

Tier 0:
- PKT-LFC-001

Tier 1:
- PKT-LFC-002

Tier 2 (parallel window):
- PKT-LFC-003
- PKT-LFC-004

Tier 3 (parallel window):
- PKT-LFC-005
- PKT-LFC-006

Tier 4:
- PKT-LFC-007

### Phase 2 topological order

Tier 0:
- PKT-RLS-001

Tier 1:
- PKT-RLS-002

Tier 2 (parallel window):
- PKT-RLS-003
- PKT-RLS-007

Tier 3:
- PKT-RLS-004

Tier 4:
- PKT-RLS-005

Tier 5:
- PKT-RLS-006

Tier 6:
- PKT-RLS-008

---

## Parallelization guidance

### Phase 0 parallel windows
- after PKT-FND-001: PKT-FND-002 and PKT-FND-003 may be prepared
- after PKT-FND-002 and PKT-FND-003: PKT-FND-004 and PKT-FND-006 may proceed independently
- PKT-FND-005 follows once scaffold + schemas are ready
- PKT-FND-007 closes the phase

### Phase 1 parallel windows
- PKT-LFC-003 and PKT-LFC-004 can run in parallel after PKT-LFC-002 is verified
- PKT-LFC-005 and PKT-LFC-006 can run in parallel after the required predecessors are verified

### Phase 2 parallel windows
- PKT-RLS-003 and PKT-RLS-007 can run in parallel after PKT-RLS-002 / PKT-RLS-001 prerequisites are satisfied
- PKT-RLS-008 is the integration capstone and must not start early

---

## Phase gate reminders

### Phase 0 must prove
- validators run in CI
- lifecycle CLI stub emits deterministic output
- fixtures validate or fail as expected
- packet dependency validator works
- no contract fields need further change for Phase 1

### Phase 1 must prove
- fresh install, update dispatch, cutover planning, and uninstall planning all work in sandbox repos
- `.audiagentic/installed.json` is written atomically and validates
- `.audiagentic/` project-local config creation is deterministic
- workflow detection/rename policy is verified
- migration outcomes are emitted deterministically

### Phase 2 must prove
- release core works without jobs, Discord, or providers
- duplicate fragment handling is deterministic
- sync is idempotent and lock-safe, including stale-lock recovery
- finalization writes checkpoints and is restart-safe
- Release Please baseline management is deterministic
- end-to-end release flow integration tests pass

---

## What a worker should do before starting in Phase 0–2

1. Read `31_Build_Status_and_Work_Registry.md`.
2. Confirm the packet is `READY_TO_START`.
3. Confirm every dependency is `VERIFIED`.
4. Read the phase build book.
5. Read the packet build sheet.
6. Read the governing spec docs named by the packet.
7. Claim the packet in the registry.
8. Create a dedicated branch/worktree.
9. Implement only within owned boundaries.
10. Update the registry as status changes.

---

## What not to duplicate

Do not create local copies of:
- packet dependency state
- current packet ownership state
- phase gate state
- build completion state

Those all belong in:
- `31_Build_Status_and_Work_Registry.md`

Use this file and the registry together; do not invent parallel trackers.


## Extension note

The .2 extension adds prompt-launch and review-related contract/lifecycle/release work to Phases 0–2. These packets remain blocked until the .1 provider/model contract line is frozen.
