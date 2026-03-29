# Build Status and Work Registry

This document is the **single operational source of truth** for current build state.

Any developer or agent starting work must use this document to determine:
- what is complete
- what is in progress
- what is blocked
- what is safe to begin next
- which packet or module is already claimed
- which specification and implementation docs govern the work

If this document is not updated, the implementation state is considered unreliable.

---

## Mandatory usage rules

1. **Read this document first** before starting any work.
2. Do not start a packet or module unless its dependencies are satisfied.
3. Do not start work that is already `CLAIMED`, `IN_PROGRESS`, or `READY_FOR_REVIEW` by someone else.
4. Update this document at every state transition.
5. If work changes scope, dependencies, or ownership boundaries, update this document and follow `25_Change_Control_and_Document_Update_Rules.md`.
6. If a packet is merged, update this document to `MERGED` and then to `VERIFIED` once the phase gate evidence is complete.
7. If a packet cannot proceed, mark it `BLOCKED` with a short reason and the blocking dependency.

---

## Status values

| Status | Meaning | May start work? |
|---|---|---|
| `READY_TO_START` | all dependencies satisfied and no current owner | yes |
| `WAITING_ON_DEPENDENCIES` | blocked by required packets or phase gate | no |
| `CLAIMED` | owner has reserved the packet and is preparing to work | no |
| `IN_PROGRESS` | implementation actively underway | no |
| `BLOCKED` | owner cannot progress until blocker is resolved | no |
| `READY_FOR_REVIEW` | implementation complete and awaiting review/merge | no |
| `MERGED` | code/docs merged but gate verification not yet recorded | no |
| `VERIFIED` | merged and verified against packet acceptance criteria | yes for dependents |
| `DEFERRED_DRAFT` | intentionally pushed to later phase or draft-only | no |
| `CANCELLED` | removed from active plan | no |

---

## Required fields for each active work item

Each row in the registry must contain:
- packet id
- phase
- title
- current status
- owner
- worktree or branch
- dependency state
- primary spec refs
- primary implementation refs
- last update date
- notes / blockers / PR / merge reference

---

## How to update this registry

### When claiming work
- set status to `CLAIMED`
- record owner
- record branch/worktree
- add date
- verify dependencies are already `VERIFIED`

### When coding starts
- set status to `IN_PROGRESS`
- add short note describing what is being built first

### When a blocker is found
- set status to `BLOCKED`
- identify the exact blocker packet or contract
- do not continue around the blocker unless change control approves it

### When implementation is complete
- set status to `READY_FOR_REVIEW`
- record PR/commit reference
- note which fixtures/tests were added

### After merge
- set status to `MERGED`
- then set to `VERIFIED` once acceptance checks and gate evidence pass

---

## Source documents every worker must check

- `01_Master_Implementation_Roadmap.md`
- `02_Phase_Gates_and_Exit_Criteria.md`
- `03_Target_Codebase_Tree.md`
- `05_Module_Ownership_and_Parallelization_Map.md`
- `13_Packet_Execution_Rules.md`
- `20_Packet_Dependency_Graph.md`
- the packet build sheet itself

---

## Current program state

### Phase state summary

| Phase | State | Notes |
|---|---|---|
| Phase 0 | `VERIFIED` | phase 0 gate complete |
| Phase 1 | `IN_PROGRESS` | PKT-LFC-001 verified |
| Phase 2 | `WAITING_ON_DEPENDENCIES` | cannot start until Phase 1 gate is verified |
| Phase 3 | `WAITING_ON_DEPENDENCIES` | cannot start until Phase 2 gate is verified |
| Phase 4 | `WAITING_ON_DEPENDENCIES` | cannot start until Phase 3 gate is verified |
| Phase 5 | `WAITING_ON_DEPENDENCIES` | cannot start until Phase 4 gate is verified |
| Phase 6 | `WAITING_ON_DEPENDENCIES` | cannot start until Phase 5/6 preconditions are satisfied |

---

## Packet registry

### Phase 0 — Contracts and Scaffolding

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-FND-001 | Canonical IDs + naming validator | VERIFIED | Codex | workspace | none | 03, 06, packet | 2026-03-29 | tests: tests/unit/contracts/test_validate_ids.py; fixtures: docs/examples/fixtures/canonical-ids.valid.json |
| PKT-FND-002 | Schema package + validator | VERIFIED | Codex | workspace | needs PKT-FND-001 VERIFIED | 03, 06, packet | 2026-03-29 | tests: tests/unit/contracts/test_schema_validation.py; fixtures: docs/examples/fixtures/*.valid.json + *.invalid.json |
| PKT-FND-003 | File ownership matrix + glossary | VERIFIED | Codex | workspace | needs PKT-FND-001 VERIFIED | 18, 19, packet | 2026-03-29 | tests: tests/unit/contracts/test_docs_consistency.py; fixtures: docs/examples/fixtures/ownership-matrix.sample.json |
| PKT-FND-004 | Example project scaffold | VERIFIED | Codex | workspace | needs PKT-FND-002 + PKT-FND-003 VERIFIED | 04, packet | 2026-03-29 | tests: tests/integration/test_example_scaffold.py; tool: tools/seed_example_project.py |
| PKT-FND-005 | Lifecycle CLI stub + checkpoints | VERIFIED | Codex | workspace | needs PKT-FND-002 + PKT-FND-004 VERIFIED | 05, packet | 2026-03-29 | tests: tests/integration/lifecycle/test_stub.py; tools: tools/lifecycle_stub.py |
| PKT-FND-006 | Error envelope + error codes | VERIFIED | Codex | workspace | needs PKT-FND-002 VERIFIED | 20, packet | 2026-03-29 | tests: tests/unit/contracts/test_error_envelope.py; fixtures: docs/examples/fixtures/error-envelope.*.json |
| PKT-FND-007 | CI validators + packet dependency validation | VERIFIED | Codex | workspace | needs PKT-FND-001 + PKT-FND-002 + PKT-FND-006 VERIFIED | 19, 20, packet | 2026-03-29 | tests: tests/integration/contracts/test_ci_validators.py; workflows: ci-contracts.yml, ci-tests.yml, ci-destructive-plan.yml |

### Phase 1 — Lifecycle and Project Enablement

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-LFC-001 | Installed-state detector | VERIFIED | Codex | workspace | needs Phase 0 VERIFIED | 05, 07, packet | 2026-03-29 | tests: tests/unit/lifecycle/test_detector.py; fixtures: docs/examples/fixtures/installed-state.fixtures.json |
| PKT-LFC-002 | Lifecycle manifest + checkpoint writer | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-LFC-001 VERIFIED | 05, packet | 2026-03-29 | |
| PKT-LFC-003 | Fresh install apply + validate | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-LFC-001 + PKT-LFC-002 VERIFIED | 05, packet | 2026-03-29 | |
| PKT-LFC-004 | Update dispatcher + version selection | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-LFC-001 + PKT-LFC-002 VERIFIED | 05, packet | 2026-03-29 | |
| PKT-LFC-005 | Legacy cutover | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-LFC-001 + PKT-LFC-002 + PKT-LFC-003 VERIFIED | 05, 15, packet | 2026-03-29 | |
| PKT-LFC-006 | Uninstall current AUDiaGentic | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-LFC-003 + PKT-LFC-004 VERIFIED | 05, packet | 2026-03-29 | |
| PKT-LFC-007 | Document migration outcomes + reports | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-LFC-005 VERIFIED | 15, packet | 2026-03-29 | |

### Phase 2 — Release / Audit / Ledger / Release Please

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-RLS-001 | Record fragment per change event | WAITING_ON_DEPENDENCIES | Unassigned | - | needs Phase 1 VERIFIED | 09, 13, packet | 2026-03-29 | |
| PKT-RLS-002 | Sync current release ledger with lock + manifest | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-RLS-001 VERIFIED | 09, packet | 2026-03-29 | |
| PKT-RLS-003 | Regenerate current release summary | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-RLS-002 VERIFIED | 09, packet | 2026-03-29 | |
| PKT-RLS-004 | Generate audit + check-in summaries | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-RLS-002 + PKT-RLS-003 VERIFIED | 09, packet | 2026-03-29 | |
| PKT-RLS-005 | Finalize release with exactly-once append | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-RLS-002 + PKT-RLS-003 + PKT-RLS-004 VERIFIED | 09, 10, packet | 2026-03-29 | |
| PKT-RLS-006 | Release Please baseline workflow/config management | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-LFC-003 + PKT-RLS-005 VERIFIED | 10, 23, packet | 2026-03-29 | |
| PKT-RLS-007 | Convert legacy changelog/history to ledger events | WAITING_ON_DEPENDENCIES | Unassigned | - | needs PKT-LFC-005 + PKT-RLS-001 VERIFIED | 09, 15, packet | 2026-03-29 | |
| PKT-RLS-008 | End-to-end release flow integration tests | WAITING_ON_DEPENDENCIES | Unassigned | - | needs all Phase 2 RLS packets VERIFIED | 24, packet | 2026-03-29 | |

### Later phases

Later phases should continue this registry pattern using the same fields and status rules. Work may be listed now as `WAITING_ON_DEPENDENCIES`, but active claiming should not occur until earlier phase gates are closed.

| Phase | Packets | Current State |
|---|---|---|
| Phase 3 | PKT-JOB-001 .. PKT-JOB-006 | WAITING_ON_DEPENDENCIES |
| Phase 4 | PKT-PRV-001 .. PKT-PRV-010, PKT-SRV-001 | WAITING_ON_DEPENDENCIES |
| Phase 5 | PKT-DSC-001 .. PKT-DSC-004 | WAITING_ON_DEPENDENCIES |
| Phase 6 | PKT-MIG-001 .. PKT-MIG-003 | WAITING_ON_DEPENDENCIES |

---

## Build-status maintenance rules for reviews and merges

Every PR or merge request must update this file when:
- a packet is claimed
- work starts
- work is blocked
- work is ready for review
- work is merged
- work is verified

Every review summary should reference the current packet status here before commenting on readiness.

---

## Verification query for a new worker

Before starting, answer these from this document:
1. Is the packet already claimed or in progress?
2. Are all dependencies verified?
3. Is the phase unlocked?
4. What docs govern this packet?
5. Which files am I allowed to own?
6. What tests and fixtures am I expected to add?

If any answer is unclear, do not start coding.
