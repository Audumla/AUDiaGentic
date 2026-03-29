# New Agent or Developer — Start Here

This is the mandatory onboarding document for anyone starting work on AUDiaGentic.

The goal is to prevent duplicated work, hidden contract changes, and accidental overlap between agents or developers.

---

## The rule

Do not begin work by reading a random packet first.

Begin with the **current build state**, then confirm the packet is available, then read the governing contracts, then claim the work.

---

## Step-by-step startup procedure

### Step 1 — read the current build state
Read:
- `31_Build_Status_and_Work_Registry.md`

Confirm:
- which phase is currently open
- which packets are already claimed or active
- which packet is the next legal starting point

If the packet you wanted is not `READY_TO_START`, do not begin it.

### Step 2 — confirm the dependency chain
Read:
- `20_Packet_Dependency_Graph.md`
- the packet row in `31_Build_Status_and_Work_Registry.md`

Confirm:
- all direct dependencies are `VERIFIED`
- no hidden contract packet is still in progress
- the phase gate for the previous phase is closed

### Step 3 — read the governing docs
Always read these before touching code:
- `03_Target_Codebase_Tree.md`
- `05_Module_Ownership_and_Parallelization_Map.md`
- `13_Packet_Execution_Rules.md`
- your assigned packet build sheet

Also read the relevant spec docs referenced by the packet.

### Step 4 — claim the work
Before starting implementation:
- update `31_Build_Status_and_Work_Registry.md`
- set the packet to `CLAIMED`
- add your name/agent name
- add the branch or worktree name
- add the current date

If you have not claimed it in the registry, you do not own it.

### Step 5 — create isolated work
Use a new branch or worktree.
Suggested naming:
- `pkt-fnd-001-<owner>`
- `pkt-lfc-003-<owner>`
- `pkt-rls-002-<owner>`

Do not mix multiple packets in the same branch unless the roadmap or phase lead explicitly approves it.

### Step 6 — implement only within owned boundaries
Read the packet’s ownership section and obey it.

You may:
- create or modify files listed under ownership
- read contract docs and dependency outputs
- add required fixtures and tests in packet-owned locations

You may not:
- change files owned by another packet
- widen scope to solve a later-phase problem
- silently change shared contracts
- write tracked release docs directly from jobs or later-phase overlays

### Step 7 — keep the build state current
As you work, update `31_Build_Status_and_Work_Registry.md`:
- `CLAIMED` → `IN_PROGRESS`
- `IN_PROGRESS` → `BLOCKED` if blocked
- `IN_PROGRESS` → `READY_FOR_REVIEW` when done
- `READY_FOR_REVIEW` → `MERGED`
- `MERGED` → `VERIFIED` after acceptance checks complete

### Step 8 — finish with evidence
When you mark a packet `READY_FOR_REVIEW`, note:
- tests added
- fixtures added
- docs updated
- PR/commit reference
- any follow-up items

---

## If you need to start a new module

Do **not** create a new module just because it seems useful.

Follow this process:
1. Check `03_Target_Codebase_Tree.md`.
2. If the module already exists in the target tree, use the planned location.
3. If the module does not exist, do not add it silently.
4. Raise a change request using `25_Change_Control_and_Document_Update_Rules.md`.
5. Update the target codebase tree before adding the module.
6. Update the build-status registry if a new packet or changed ownership boundary is approved.

This keeps the codebase structure stable for parallel work.

---

## If you discover a contract issue

Stop and decide whether it is:
- a clear bug in documentation or schema, or
- a design change

Then follow `25_Change_Control_and_Document_Update_Rules.md`.

Do not work around the issue locally in code.

---

## Minimum reading set by packet type

### For Phase 0 work
Read:
- `27_Phase_0_Kickoff_Checklist.md`
- `06_Phase_0_Build_Book.md`
- your packet file
- relevant contract docs

### For Phase 1 work
Read:
- `07_Phase_1_Build_Book.md`
- `05_Installation_Update_Cutover_and_Uninstall.md`
- your packet file

### For Phase 2 work
Read:
- `08_Phase_2_Build_Book.md`
- `09_Release_Audit_and_Change_Ledger.md`
- `10_Release_Please_Baseline_Workflow_Management.md`
- your packet file

---

## Definition of “safe to begin”

A packet is safe to begin only when:
- it is listed in the build registry
- its status is `READY_TO_START`
- dependencies are verified
- phase gate prerequisites are satisfied
- you have claimed it
- you understand the ownership boundary and outputs

If one of these is missing, the correct action is to clarify the state first — not to start coding.

---

## Active Progress

| Date | Phase | Packet | Status | Notes |
|---|---|---|---|---|
| 2026-03-29 | Phase 1 | PKT-LFC-002 | VERIFIED | Manifest + checkpoint semantics; installed-state schema + error-envelope schema added |
| 2026-03-29 | Phase 1 | PKT-LFC-003 | VERIFIED | Fresh install apply + e2e tests | 
| 2026-03-29 | Phase 1 | PKT-LFC-004 | VERIFIED | Update dispatch module + unit tests |
| 2026-03-29 | Phase 1 | PKT-LFC-005 | VERIFIED | Legacy cutover apply + report tests |
| 2026-03-29 | Phase 1 | PKT-LFC-006 | VERIFIED | Uninstall semantics + e2e tests |
| 2026-03-29 | Phase 1 | PKT-LFC-007 | VERIFIED | Doc migration classification + report tests |
| 2026-03-29 | Phase 2 | PKT-RLS-001 | VERIFIED | Fragment recorder + unit tests |
| 2026-03-29 | Phase 2 | PKT-RLS-002 | VERIFIED | Ledger sync + lock integration tests (exit code anomaly noted) |
