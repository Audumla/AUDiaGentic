# New Agent or Developer — Start Here

This is the mandatory onboarding document for anyone starting work on AUDiaGentic.

The goal is to prevent duplicated work, hidden contract changes, and accidental overlap between agents or developers.

---

## The rule

Do not begin work by reading a random packet first.

Begin with the **current build state**, then confirm the packet is available, then read the governing contracts, then claim the work.

---

## Feature extension numbering

This project records doc-changing feature extensions with a decimal suffix so later updates do not collide.

Current extension slots:
- `.1` = provider definition extensions, including access-mode and model catalog work
- `.2` = prompt-tagged workflow launch, ad hoc execution, and structured review loop
- `.3` = prompt shorthand and default-launch enhancements, including provider shorthand and inferred default subjects/models
- `.4` = provider prompt-tag surface recognition and synchronization across provider surfaces
- `.5` = provider tag execution compliance and isolated provider implementation docs
- `.6` = provider prompt-trigger launch behavior, agent instruction surfaces, and wrapper/bridge invocation
- `.7` = provider availability, auto-install, and bootstrap orchestration
- `.8` = project release bootstrap and workflow activation using the project's own release machinery
- `.9` = provider live stream and progress capture, with Cline and Codex as the first-wave validation providers
- `.10` = provider live input and interactive session control, with Cline and Codex as the first-wave validation providers
- `.11` = provider structured completion and result normalization, with Cline and Codex as the first-wave validation providers
- `.12` = provider optimization and shared workflow extensibility, with scripts/skills/MCP/wrapper reuse reserved for later token-reduction work
- prompt tag names, provider shorthands, and argument aliases are configurable through `.audiagentic/prompt-syntax.yaml`

Do not invent a new suffix until the build registry and roadmap are updated first.

---

## Current operational starting point

At the time of this pack:
- `.1` work is complete
- `.2` work is complete for the first executable pass, with `@adhoc` intentionally feature-gated
- `.3` work is complete for the first shorthand/default-launch pass
- `.4` shared surface-contract work is implemented
- `.5` provider execution compliance docs are staged as the isolated provider-specific implementation layer
- `.6` prompt-trigger launch behavior is drafted as the next feature slice
- `.7` provider availability and auto-install orchestration is drafted as the next feature slice
- `.8` project release bootstrap and workflow activation is complete so the project can install itself using its own release processes
- `.9` provider live stream and progress capture is drafted so AUDiaGentic can own console mirroring and runtime persistence while providers emit progress
- `.10` provider live input and interactive session control is in progress; the shared harness is implemented and test-covered, and Cline/Codex are next
- `.11` provider structured completion and result normalization is drafted so Cline, Codex, and the remaining providers can return canonical review/output payloads without duplicating the shared bridge harness
- `.12` provider optimization and shared workflow extensibility is drafted so shared scripts, skills, MCP tools, and wrappers can reduce token usage without locking in the future workflow model
- a separate later extension line now exists for Phase 7 through Phase 11: node execution, discovery/registry, distributed eventing/control, coordinator consumption, and external tool connectivity; these are additive backend seams and remain outside the baseline MVP
- Phase 5 Discord overlay packets are ready to start once claimed
- the build registry is the source of truth for any remaining later-phase work

That means a new implementor should begin by reading `31_Build_Status_and_Work_Registry.md` and then claim the next later-phase packet that is actually `READY_TO_START`.

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
- `pkt-job-008-<owner>`

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

### For Phase 0 / 0.1 / 0.2 work
Read:
- `27_Phase_0_Kickoff_Checklist.md`
- `06_Phase_0_Build_Book.md`
- `03_Common_Contracts.md`
- `26_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md` when working on `.2`
- your packet file

### For Phase 1 / 1.1 / 1.2 work
Read:
- `07_Phase_1_Build_Book.md`
- `05_Installation_Update_Cutover_and_Uninstall.md`
- your packet file

### For Phase 2 / 2.1 / 2.2 work
Read:
- `08_Phase_2_Build_Book.md`
- `09_Release_Audit_and_Change_Ledger.md`
- `10_Release_Please_Baseline_Workflow_Management.md`
- your packet file

### For Phase 3 / 3.1 / 3.2 / 3.3 work
Read:
- `09_Phase_3_Build_Book.md`
- `08_Agent_Jobs_MVP.md`
- `12_Workflow_Profiles_and_Extensibility.md`
- `35_Phase_3_2_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md` when working on `.2`
- `37_Phase_3_3_Prompt_Tagged_Workflow_Shortcuts_and_Defaults.md` when working on `.3`
- your packet file

### For Phase 4 / 4.1 / 4.2 / 4.3 work
Read:
- `06_Phase_4_Providers_and_Optional_Server_Foundation.md`
- `10_Phase_4_Build_Book.md`
- `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md` when working on `.4`
- `38_Phase_4_3_Provider_Prompt_Tag_Surface_Integration.md` when working on `.4`
- `10_Prompt_Tag_Surface_Integration_Shared.md` when working on `.4`
- `34_DRAFT_Provider_Live_Stream_and_Progress_Capture.md` when working on `.9`
- `45_Phase_4_9_Provider_Live_Stream_and_Progress_Capture.md` when working on `.9`
- `35_DRAFT_Provider_Live_Input_and_Interactive_Session_Control.md` when working on `.10`
- `46_Phase_4_10_Provider_Live_Input_and_Interactive_Session_Control.md` when working on `.10`
- `28_Provider_Tag_Execution_Compliance_Model.md` when working on `.5`
- `11_Provider_Tag_Execution_Conformance_Matrix.md` when working on `.5`
- `39_Phase_4_4_Provider_Tag_Execution_Implementation.md` when working on `.5`
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
