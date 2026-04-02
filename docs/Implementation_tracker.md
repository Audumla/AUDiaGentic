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
- `.2` = prompt-tagged workflow launch, structured review loop, and feature-gated ad hoc execution
- `.3` = prompt shorthand and default-launch enhancements, including provider shorthand and inferred default subjects/models
- `.4` = provider prompt-tag surface recognition and synchronization across provider surfaces
- `.5` = provider tag execution compliance and isolated provider implementation docs
- `.6` = provider prompt-trigger launch behavior, agent instruction surfaces, and wrapper/bridge invocation
- `.7` = provider availability, auto-install, and bootstrap orchestration
- `.8` = project release bootstrap and workflow activation using the project's own release machinery
- `Phase 1.4` = installable project baseline and managed asset synchronization for clean/existing project setup
- `.9` = provider live stream and progress capture, with Cline and Codex as the first-wave validation providers; part of the shared 4.9–4.11 provider session I/O and completion tranche for implementation reuse only
- `.10` = provider live input and interactive session control, with Cline and Codex as the first-wave validation providers; part of the shared 4.9–4.11 provider session I/O and completion tranche for implementation reuse only
- `.11` = provider structured completion and result normalization, with Cline and Codex as the first-wave validation providers; part of the shared 4.9–4.11 provider session I/O and completion tranche for implementation reuse only
- `.12` = provider optimization and shared workflow extensibility, with scripts/skills/MCP/wrapper reuse reserved for later token-reduction work
- phase 4.12 optimization is script-first and template-driven for repeatable operations; agents should provide only the minimum intent or parameters needed by the helper
- `.13` = canonical prompt entry and bridge end state, where every supported provider and prompt-entry surface converges on the same repo-owned bridge/launcher contract
- prompt tag names, provider shorthands, and argument aliases are configurable through `.audiagentic/prompt-syntax.yaml`
- prompt-launch now merges project-level default stream and input controls so live output capture and interactive turns stay AUDiaGentic-owned
- Codex, Cline, and Gemini provider configs now use longer timeout defaults to give the streaming review path room to finish long-running tasks
- a separate later extension line now exists for Phase 7 through Phase 11: node execution, discovery/registry, federation/control, coordinator consumption, and connector connectivity; these remain additive backend seams and do not replace the baseline phases

Stable release baseline:
- `stable-release-20260331` at merge commit `4e01b4ef962cf80c8f6fe912f1b6a7cba22bcb32`

Do not invent a new suffix until the build registry and roadmap are updated first.

---

## Current operational starting point

At the time of this pack:
- `.1` work is complete
- `.2` work is complete for the first executable pass, with `@adhoc` intentionally feature-gated
- `.3` work is complete for the first shorthand/default-launch pass
- `.4` shared surface-contract work is implemented
- `.5` provider execution compliance docs are staged as the isolated provider-specific implementation layer
- `.6` prompt-trigger launch behavior is now drafted, with a realistic rollout assessment that splits first-wave and wrapper-first providers; the shared bridge harness is now implemented and the Claude/Cline provider paths have started
- the prompt-calling mechanics map is now explicit, starting with Codex as the reference bridge/skills path and then mirroring the other provider surfaces
- Codex now has an explicit preflight contract that validates `AGENTS.md` and the canonical skill files before launch
- `.7` provider auto-install orchestration is now drafted and awaiting implementation packets
- `.8` project release bootstrap and workflow activation is complete so the project can install itself using its own release processes
- `Phase 1.4` is now defined and its first packet has frozen the managed install baseline inventory so lifecycle/bootstrap can converge on the repository's real installable baseline instead of a minimal scaffold
- `.9` provider live stream and progress capture is now implementation-ready at the spec/build-doc level so AUDiaGentic can own console mirroring and runtime persistence while providers emit progress; it is part of the shared 4.9–4.11 provider session I/O and completion tranche
- `.10` provider live input and interactive session control is in progress; the shared harness is implemented and test-covered, and Cline/Codex are next; it is part of the shared 4.9–4.11 provider session I/O and completion tranche
- prompt-syntax profiles now control the canonical shorthand names, so tag and argument aliases can be adjusted without changing the parser code
- prompt-launch now applies default stream and input controls before provider execution, giving the shared bridge ownership of live output and interactive session capture
- provider timeout defaults are now extended for Codex, Cline, and Gemini so review sessions can run long enough to finish while still streaming progress
- Cline review launches currently execute through the bridge, but still need prompt-shape hardening to reliably return structured JSON instead of a synthetic review bundle
- `.11` provider structured completion and result normalization is now implementation-ready and packetized so Cline, Codex, and the remaining providers can return canonical review/output payloads without duplicating the shared bridge harness; `.12` provider optimization and shared workflow extensibility follows as the docs-only token-reduction slice; `.13` now explicitly states the end-state for all supported providers and prompt-entry surfaces
- Phase 2.3 project release bootstrap and workflow activation is verified and using the project's own release machinery
- later phase work beyond `.13` remains deferred until additional packet definitions are added
- the current open follow-ons are the remaining Phase 1.4 baseline-sync engine packets, Phase 4.7 provider auto-install orchestration, Phase 4.9 provider live stream and progress capture, Phase 4.10 provider live input and interactive session control, PKT-PRV-054 session provenance redaction and secure-session reference handling, Phase 4.11 provider structured completion and result normalization, Phase 4.12 provider optimization and shared workflow extensibility, Phase 4.13 canonical prompt entry and bridge end state, Phase 1.3 provider auto-install policy persistence, the remaining provider-specific prompt-calling hardening, and the optional hard-kill extension for job control

That means new implementors should use the build registry for the next legal packet rather than reopening `.1`, `.2`, or `.3`.

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

### For Phase 3 / 3.1 / 3.2 / 3.3 / 3.4 work
Read:
- `09_Phase_3_Build_Book.md`
- `08_Agent_Jobs_MVP.md`
- `12_Workflow_Profiles_and_Extensibility.md`
- `35_Phase_3_2_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md` when working on `.2`
- `37_Phase_3_3_Prompt_Tagged_Workflow_Shortcuts_and_Defaults.md` when working on `.3`
- `32_DRAFT_Job_Control_and_Running_Job_Cancellation.md` when working on `.4`
- your packet file

### For Phase 4 / 4.1 / 4.2 / 4.3 work
Read:
- `06_Phase_4_Providers_and_Optional_Server_Foundation.md`
- `10_Phase_4_Build_Book.md`
- `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md` when working on `.4`
- `38_Phase_4_3_Provider_Prompt_Tag_Surface_Integration.md` when working on `.4`
- `10_Prompt_Tag_Surface_Integration_Shared.md` when working on `.4`
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
| 2026-03-29 | Phase 2 | PKT-RLS-003 | VERIFIED | Current release summary regeneration |
| 2026-03-29 | Phase 2 | PKT-RLS-004 | VERIFIED | Audit + check-in summaries |
| 2026-03-29 | Phase 2 | PKT-RLS-005 | VERIFIED | Finalize release exactly-once append |
| 2026-03-29 | Phase 2 | PKT-RLS-006 | VERIFIED | Release Please baseline workflow management |
| 2026-03-29 | Phase 2 | PKT-RLS-007 | VERIFIED | Legacy changelog import |
| 2026-03-29 | Phase 2 | PKT-RLS-008 | VERIFIED | End-to-end release flow tests |
| 2026-03-30 | Phase 3 | PKT-JOB-001 | VERIFIED | Job record store + state machine; tests: tests/unit/jobs/test_state_machine.py |
| 2026-03-30 | Phase 3 | PKT-JOB-002 | VERIFIED | Workflow profile loader + validator; tests: tests/unit/jobs/test_profiles.py; fixtures: workflow-overrides.*.yaml |
| 2026-03-30 | Phase 3 | PKT-JOB-003 | VERIFIED | Packet runner; tests: tests/integration/jobs/test_packet_runner.py |
| 2026-03-30 | Phase 3 | PKT-JOB-004 | VERIFIED | Stage execution contract + persistence; tests: tests/unit/jobs/test_stage_contract.py; fixtures: stage-result.*.json |
| 2026-03-30 | Phase 3 | PKT-JOB-005 | VERIFIED | Job approvals + timeout handling; tests: tests/integration/jobs/test_job_approvals.py |
| 2026-03-30 | Phase 3 | PKT-JOB-006 | VERIFIED | Release bridge integration; tests: tests/integration/jobs/test_release_bridge.py |
| 2026-03-30 | Phase 4 | PKT-PRV-001 | VERIFIED | Provider registry + descriptor validation; tests: tests/unit/providers/test_registry.py |
| 2026-03-30 | Phase 4 | PKT-PRV-002 | VERIFIED | Provider selection + health checks; tests: tests/integration/providers/test_selection.py |
| 2026-03-30 | Phase 4 | PKT-PRV-003 | VERIFIED | local-openai adapter; tests: tests/integration/providers/test_local_openai.py |
| 2026-03-30 | Phase 4 | PKT-PRV-004 | VERIFIED | claude adapter; tests: tests/integration/providers/test_claude.py; live wrapper smoke test verified; hook/skills assets still needed for full native-intercept rollout |
| 2026-03-30 | Phase 4 | PKT-PRV-005 | VERIFIED | codex adapter; tests: tests/integration/providers/test_codex.py; live wrapper smoke test verified; task payload enrichment still a follow-up |
| 2026-03-30 | Phase 4 | PKT-PRV-006 | VERIFIED | gemini adapter; tests: tests/integration/providers/test_gemini.py |
| 2026-03-30 | Phase 4 | PKT-PRV-007 | VERIFIED | copilot adapter; tests: tests/integration/providers/test_copilot.py |
| 2026-03-30 | Phase 4 | PKT-PRV-008 | VERIFIED | continue adapter; tests: tests/integration/providers/test_continue.py |
| 2026-03-30 | Phase 4 | PKT-PRV-009 | VERIFIED | cline adapter; tests: tests/integration/providers/test_cline.py |
| 2026-03-30 | Phase 4 | PKT-PRV-010 | VERIFIED | provider/job seam tests; tests: tests/integration/providers/test_job_provider_seam.py |
| 2026-03-30 | Phase 4 | PKT-SRV-001 | VERIFIED | optional server seam; tests: tests/unit/server/test_service_boundary.py |
| 2026-03-30 | Phase 4 | PKT-PRV-011 | VERIFIED | provider access-mode contract + health config rules; tests: tests/unit/contracts/test_schema_validation.py; tests/integration/providers/test_selection.py; tests/integration/test_example_scaffold.py; tests/e2e/lifecycle/test_fresh_install.py |
| 2026-03-30 | Phase 4.1 | PKT-PRV-012 | VERIFIED | provider model catalog + selection rules; tests: tests/unit/providers/test_model_catalog.py; tests/integration/providers/test_model_selection.py |
| 2026-03-30 | Phase 4.2 | PKT-PRV-013 | VERIFIED | provider CLI/status inspection; tests: tests/unit/providers/test_provider_status.py; tests/integration/providers/test_provider_status_cli.py |
| 2026-03-30 | Phase 4.3 | PKT-PRV-014 | VERIFIED | provider prompt-tag surface contract, schema, fixtures, semantic validation, and status summary implemented; provider-specific rollout guidance now lives in Phase 4.4 |
| 2026-03-30 | Phase 4.4 | PKT-PRV-022 | VERIFIED | provider execution compliance model, conformance matrix, and isolated provider implementation docs added |
| 2026-03-30 | Phase 4.6 | PKT-PRV-031 | VERIFIED | provider prompt-trigger launch behavior; shared trigger bridge and provider-specific instruction surfaces drafted and implemented for the shared bridge harness |
| 2026-03-30 | Phase 4.6 | PKT-PRV-032 | READY_FOR_REVIEW | Codex prompt-trigger bridge surface implemented with repo-local `AGENTS.md` and `.agents/skills` guidance |
| 2026-03-30 | Phase 4.6 | PKT-PRV-033 | READY_FOR_REVIEW | Claude prompt-trigger bridge surface implemented with repo-local `CLAUDE.md` and `.claude/rules` guidance |
| 2026-03-30 | Phase 4.6 | PKT-PRV-034 | READY_FOR_REVIEW | Gemini prompt-trigger bridge surface implemented with repo-local `GEMINI.md` guidance |
| 2026-03-30 | Phase 4.6 | PKT-PRV-035 | READY_FOR_REVIEW | GitHub Copilot prompt-trigger bridge surface implemented with repo-local `.github/copilot-instructions.md`, prompt files, and agent files |
| 2026-03-30 | Phase 4.6 | PKT-PRV-037 | READY_FOR_REVIEW | Cline prompt-trigger bridge surface implemented with repo-local `.clinerules` guidance |
| 2026-03-30 | Phase 4.6 | PKT-PRV-038 | READY_FOR_REVIEW | local-openai/qwen prompt-trigger bridge surface implemented with repo-local bridge wrappers |
| 2026-03-30 | Phase 4.7 | PKT-PRV-039 | DEFERRED_DRAFT | provider availability and auto-install orchestration; shared install policy and provider-specific bootstrap packets drafted |
| 2026-03-31 | Phase 4.9 | PKT-PRV-048 | DEFERRED_DRAFT | shared live-stream capture contract drafted; console mirroring and runtime persistence remain AUDiaGentic-owned |
| 2026-03-31 | Phase 4.9 | PKT-PRV-049 | DEFERRED_DRAFT | Codex live-stream capture packet drafted as a first-wave validation provider |
| 2026-03-31 | Phase 4.9 | PKT-PRV-050 | DEFERRED_DRAFT | Cline live-stream capture packet drafted as a first-wave validation provider |
| 2026-03-31 | Phase 4.10 | PKT-PRV-051 | READY_FOR_REVIEW | shared live-input harness implemented with session-input persistence and a session-input CLI |
| 2026-03-31 | Phase 4.10 | PKT-PRV-052 | DEFERRED_DRAFT | Codex live-input capture packet drafted as a first-wave validation provider |
| 2026-03-31 | Phase 4.10 | PKT-PRV-053 | DEFERRED_DRAFT | Cline live-input capture packet drafted as a first-wave validation provider |
| 2026-04-02 | Phase 4.10 | PKT-PRV-054 | DEFERRED_DRAFT | session provenance redaction and secure-session reference seam captured so raw provider session keys are not treated as log-safe runtime data |
| 2026-04-02 | Phase 4.11 | PKT-PRV-056 | DEFERRED_DRAFT | shared structured-completion contract and normalization harness packetized for implementation |
| 2026-04-02 | Phase 4.11 | PKT-PRV-057 | DEFERRED_DRAFT | Codex structured-completion integration packetized for implementation |
| 2026-04-02 | Phase 4.11 | PKT-PRV-058 | DEFERRED_DRAFT | Cline structured-completion integration packetized for implementation |
| 2026-03-30 | Phase 5 | PKT-DSC-001 .. PKT-DSC-004 | READY_TO_START | Discord overlay packet headers normalized; phase 5 is ready to implement after Phase 4.4 verification |
| 2026-03-30 | Phase 0.1 | PKT-FND-008 | VERIFIED | contract/schema updates for access-mode, model catalog, model-id/model-alias |
| 2026-03-30 | Phase 1.1 | PKT-LFC-008 | VERIFIED | lifecycle updates to preserve new tracked config fields |
| 2026-03-30 | Phase 2.1 | PKT-RLS-009 | VERIFIED | release updates to summarize or omit provider/model metadata explicitly |
| 2026-03-30 | Phase 3.1 | PKT-JOB-007 | VERIFIED | job updates for provider-id, model-id, model-alias, default-model |
| 2026-03-30 | Phase 0.2 | PKT-FND-009 | VERIFIED | foundational prompt-launch contracts and schemas specified; implementation complete |
| 2026-03-30 | Phase 1.2 | PKT-LFC-009 | VERIFIED | lifecycle handling for prompt/job config persistence implemented |
| 2026-03-30 | Phase 1.3 | PKT-LFC-010 | DEFERRED_DRAFT | lifecycle preservation for provider auto-install policy fields drafted |
| 2026-03-30 | Phase 2.2 | PKT-RLS-010 | VERIFIED | release/audit reporting for prompt launch + review artifacts implemented |
| 2026-03-31 | Phase 2.3 | PKT-RLS-011 | VERIFIED | project release bootstrap and workflow activation implemented through the project's own release machinery |
| 2026-03-30 | Phase 3.2 | PKT-JOB-008 | VERIFIED | prompt-tagged launch core implemented; provider shorthand defaults and short tag aliases added; explicit `@adhoc` remains feature-gated by config |
| 2026-03-30 | Phase 3.2 | PKT-JOB-009 | VERIFIED | structured multi-review bundle + policy loop implemented |
| 2026-03-30 | Phase 3.3 | PKT-JOB-010 | VERIFIED | prompt shorthand/default-launch enhancement implemented; provider shorthand and short aliases resolve to default subjects/models |
| 2026-03-30 | Phase 3.4 | PKT-JOB-011 | READY_FOR_REVIEW | job control and running-job cancellation implemented; tests added |
