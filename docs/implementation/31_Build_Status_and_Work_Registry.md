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

The registry records the active baseline phases and the later additive extension lines in the same live format. Phase 7+ is not a separate tracking system; it is folded into this registry so the later backend seams use the same packet/phase lifecycle as the baseline work.

### Phase state summary

| Phase | State | Notes |
|---|---|---|
| Phase 0 | `VERIFIED` | phase 0 gate complete |
| Phase 0.1 | `VERIFIED` | .1 contract/schema updates for provider model catalog and model selection complete |
| Phase 0.2 | `VERIFIED` | prompt/review contract extension complete with gated `@adhoc` support |
| Phase 1 | `VERIFIED` | phase 1 gate complete |
| Phase 1.1 | `VERIFIED` | lifecycle preservation of .1 config fields complete |
| Phase 1.2 | `VERIFIED` | lifecycle preservation of prompt-launch config complete |
| Phase 1.3 | `DEFERRED_DRAFT` | lifecycle preservation of provider auto-install policy fields drafted |
| Phase 1.4 | `IN_PROGRESS` | installable project baseline and managed asset synchronization is underway; the inventory-freeze packet is ready for review and the sync-engine packets remain queued behind it |
| Phase 2 | `VERIFIED` | phase 2 gate complete |
| Phase 2.1 | `VERIFIED` | release/ledger updates for .1 fields complete |
| Phase 2.2 | `VERIFIED` | release/audit handling for prompt/review metadata complete |
| Phase 2.3 | `VERIFIED` | project release bootstrap and workflow activation complete using the project's own release machinery |
| Phase 3 | `VERIFIED` | phase 3 gate complete |
| Phase 3.1 | `VERIFIED` | incremental job updates for provider model selection complete |
| Phase 3.2 | `VERIFIED` | prompt-tagged launch, gated `@adhoc`, and review loop complete |
| Phase 3.3 | `VERIFIED` | prompt shorthand/default-launch enhancements complete |
| Phase 3.4 | `READY_FOR_REVIEW` | job control and running-job cancellation implemented and awaiting review |
| Phase 4 | `VERIFIED` | phase 4 gate complete (access-mode contract update verified) |
| Phase 4.1 | `VERIFIED` | provider model catalog + selection extensions complete |
| Phase 4.2 | `VERIFIED` | provider status/validation CLI complete |
| Phase 4.3 | `VERIFIED` | shared provider prompt-tag contract verified; provider-specific rollout guidance now lives in Phase 4.4 |
| Phase 4.4 | `VERIFIED` | provider execution compliance model and isolated provider implementation docs staged |
| Phase 4.6 | `IN_PROGRESS` | shared prompt-trigger bridge harness and first Claude/Cline/Codex/Gemini/Copilot/local-openai/Qwen provider paths implemented; provider prompt-calling mechanics map is now explicit starting with Codex; prompt-level `provider=` directives can override a surface default provider so Codex-launched prompts can intentionally hand off to Cline or another supported provider; Codex preflight now validates required `AGENTS.md` and skill files; Continue is deferred as a future integration; remaining provider instruction surfaces and wrapper/bridge rollout still need packets; realism assessment now documents first-wave vs wrapper-first providers |
| Phase 4.7 | `DEFERRED_DRAFT` | provider availability and auto-install orchestration drafted; install/bootstrap policy and packets still need refinement |
| Phase 4.9 | `IN_PROGRESS` | live stream and progress capture harness tees stdout/stderr and owns raw runtime logs; part of the shared Phase 4.9–4.11 provider session I/O and completion tranche for implementation reuse only; normalized progress-event writing remains the next step; Cline and Codex are the first-wave validation providers |
| Phase 4.10 | `IN_PROGRESS` | shared live input and interactive-session capture harness records and persists session input; part of the shared Phase 4.9–4.11 provider session I/O and completion tranche for implementation reuse only; a full live-session attachment manager is still needed for true mid-run input injection; prompt-launch now merges default stream/input controls so capture stays AUDiaGentic-owned; raw provider session keys are explicitly treated as non-log-safe follow-on material that needs a secure-session-reference seam; Cline and Codex are the first-wave validation providers |
| Phase 4.11 | `DEFERRED_DRAFT` | structured completion and result normalization is now packetized for implementation; part of the shared Phase 4.9–4.11 provider session I/O and completion tranche for implementation reuse only; Cline and Codex are the first-wave completion-normalization providers; AUDiaGentic owns final artifact persistence |
| Phase 4.12 | `DEFERRED_DRAFT` | provider optimization and shared workflow extensibility drafted; shared helper scripts, skills, MCP tools, and wrapper seams are reserved for later token-reduction work; repeatable operations are script-first and template-driven |
| Phase 4.13 | `DEFERRED_DRAFT` | canonical prompt entry and bridge end state drafted; all supported providers and prompt-entry surfaces are documented as converging on the same repo-owned bridge/launcher contract |
| Phase 7 | `WAITING_ON_DEPENDENCIES` | node execution extension is additive future work |
| Phase 8 | `WAITING_ON_DEPENDENCIES` | discovery and registry extension is additive future work |
| Phase 9 | `WAITING_ON_DEPENDENCIES` | federation and control extension is additive future work |
| Phase 10 | `WAITING_ON_DEPENDENCIES` | federation consumption seam is additive future work |
| Phase 11 | `DEFERRED_DRAFT` | external connector connectivity is a later optional extension |
| Phase 5 | `READY_TO_START` | can start once Phase 4.4 gate is verified |
| Phase 6 | `WAITING_ON_DEPENDENCIES` | cannot start until Phase 5 is complete and Phase 6 prerequisites are satisfied |

---

## Packet registry

### Phase 0 — Contracts and Scaffolding

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-FND-001 | Canonical IDs + naming validator | VERIFIED | Codex | workspace | none | 03, 06, packet | 2026-03-29 | tests: tests/unit/contracts/test_validate_ids.py; fixtures: docs/examples/fixtures/canonical-ids.sample.json; schemas: installed-state,error-envelope |
| PKT-FND-002 | Schema package + validator | VERIFIED | Codex | workspace | needs PKT-FND-001 VERIFIED | 03, 06, packet | 2026-03-29 | tests: tests/unit/contracts/test_schema_validation.py; fixtures: docs/examples/fixtures/*.valid.json + *.invalid.json; schema map supports dotted fixture names |
| PKT-FND-003 | File ownership matrix + glossary | VERIFIED | Codex | workspace | needs PKT-FND-001 VERIFIED | 18, 19, packet | 2026-03-29 | tests: tests/unit/contracts/test_docs_consistency.py; fixtures: docs/examples/fixtures/ownership-matrix.sample.json |
| PKT-FND-004 | Example project scaffold | VERIFIED | Codex | workspace | needs PKT-FND-002 + PKT-FND-003 VERIFIED | 04, packet | 2026-03-29 | tests: tests/integration/test_example_scaffold.py; tool: tools/seed_example_project.py |
| PKT-FND-005 | Lifecycle CLI stub + checkpoints | VERIFIED | Codex | workspace | needs PKT-FND-002 + PKT-FND-004 VERIFIED | 05, packet | 2026-03-29 | tests: tests/integration/lifecycle/test_stub.py; tools: tools/lifecycle_stub.py |
| PKT-FND-006 | Error envelope + error codes | VERIFIED | Codex | workspace | needs PKT-FND-002 VERIFIED | 20, packet | 2026-03-29 | tests: tests/unit/contracts/test_error_envelope.py; fixtures: docs/examples/fixtures/error-envelope.*.json; schema added |
| PKT-FND-007 | CI validators + packet dependency validation | VERIFIED | Codex | workspace | needs PKT-FND-001 + PKT-FND-002 + PKT-FND-006 VERIFIED | 19, 20, packet | 2026-03-29 | tests: tests/integration/contracts/test_ci_validators.py; workflows: ci-contracts.yml, ci-tests.yml, ci-destructive-plan.yml |

### Phase 0.1 — Incremental Contract Updates

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-FND-008 | Contract/schema updates from later phases | VERIFIED | Codex | workspace | needs Phase 0 VERIFIED + PKT-PRV-012 VERIFIED (seam: provider/model contract feeds incremental config fields) | 03, 16, packet | 2026-03-30 | contracts: access-mode, model catalog, model-id/model-alias; implemented with schema and fixture updates |

### Phase 0.2 — Prompt / Review Contract Extension

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-FND-009 | Prompt launch + review bundle contracts and schemas | VERIFIED | Codex | workspace | needs Phase 0 VERIFIED + PKT-FND-008 + PKT-PRV-012 (seam: prompt-launch and review bundle contracts align with provider launch surface) | 03, 26, 35, packet | 2026-03-30 | contracts: PromptLaunchRequest, ReviewReport, ReviewBundle, project prompt-launch policy, adhoc target |

### Phase 1 — Lifecycle and Project Enablement

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-LFC-001 | Installed-state detector | VERIFIED | Codex | workspace | needs Phase 0 VERIFIED | 05, 07, packet | 2026-03-29 | tests: tests/unit/lifecycle/test_detector.py; fixtures: docs/examples/fixtures/installed-state.fixtures.json |
| PKT-LFC-002 | Lifecycle manifest + checkpoint writer | VERIFIED | Codex | workspace | needs PKT-LFC-001 VERIFIED | 05, packet | 2026-03-29 | tests: tests/unit/lifecycle/test_manifest.py; fixtures: installed-state.*.json; checkpoints updated |
| PKT-LFC-003 | Fresh install apply + validate | VERIFIED | Codex | workspace | needs PKT-LFC-001 + PKT-LFC-002 VERIFIED | 05, packet | 2026-03-29 | tests: tests/e2e/lifecycle/test_fresh_install.py; fixture: fresh-install.sandbox.json |
| PKT-LFC-004 | Update dispatcher + version selection | VERIFIED | Codex | workspace | needs PKT-LFC-001 + PKT-LFC-002 VERIFIED | 05, packet | 2026-03-29 | tests: tests/unit/lifecycle/test_update_dispatch.py; fixture: update-dispatch.sample.json |
| PKT-LFC-005 | Legacy cutover | VERIFIED | Codex | workspace | needs PKT-LFC-001 + PKT-LFC-002 + PKT-LFC-003 VERIFIED | 05, 15, packet | 2026-03-29 | tests: tests/e2e/lifecycle/test_cutover.py; fixture: legacy-cutover.sandbox.json |
| PKT-LFC-006 | Uninstall current AUDiaGentic | VERIFIED | Codex | workspace | needs PKT-LFC-003 + PKT-LFC-004 VERIFIED | 05, packet | 2026-03-29 | tests: tests/e2e/lifecycle/test_uninstall.py; fixture: uninstall.sandbox.json |
| PKT-LFC-007 | Document migration outcomes + reports | VERIFIED | Codex | workspace | needs PKT-LFC-005 VERIFIED | 15, packet | 2026-03-29 | tests: tests/integration/lifecycle/test_doc_migration.py; fixture: doc-migration.sample.json |

### Phase 1.1 — Incremental Lifecycle Updates

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-LFC-008 | Lifecycle updates for new config fields | VERIFIED | Codex | workspace | needs Phase 1 VERIFIED + PKT-FND-008 VERIFIED | 05, packet | 2026-03-30 | preserve new tracked config fields in .audiagentic/project.yaml, .audiagentic/providers.yaml, installed.json |

### Phase 1.2 — Prompt Launch Lifecycle Updates

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-LFC-009 | Lifecycle updates for prompt-launch policy fields | VERIFIED | Codex | workspace | needs Phase 1 VERIFIED + PKT-FND-009 VERIFIED | 05, 26, 35, packet | 2026-03-30 | preserve/validate prompt-launch + workflow-overrides in .audiagentic/project.yaml |

### Phase 1.3 — Provider Auto-Install Policy Persistence

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-LFC-010 | Provider auto-install policy persistence and lifecycle roundtrip | DEFERRED_DRAFT | Codex | workspace | needs Phase 1 VERIFIED + PKT-FND-008 VERIFIED + PKT-PRV-039 DEFERRED_DRAFT (seam: lifecycle roundtrip will preserve future provider install policy fields) | 05, 30, 41, packet | 2026-03-30 | preserve provider install/bootstrap policy fields across lifecycle commands |

### Phase 1.4 — Installable Project Baseline and Managed Asset Synchronization

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-LFC-011 | Installable baseline inventory and sync-mode classification | READY_FOR_REVIEW | Codex | workspace | needs Phase 1 VERIFIED + Phase 2.3 VERIFIED | 04, 05, 48, packet | 2026-04-02 | canonical inventory table and sync modes are now frozen so install/bootstrap no longer treat the minimal scaffold as the full install baseline |
| PKT-LFC-012 | Shared baseline sync engine for lifecycle and bootstrap | WAITING_ON_DEPENDENCIES | Codex | workspace | needs PKT-LFC-011 VERIFIED | 05, 48, 56, packet | 2026-04-02 | introduce a common baseline sync seam instead of ad hoc file copy lists in lifecycle/bootstrap paths |
| PKT-LFC-013 | Converge fresh-install and release-bootstrap on baseline sync | WAITING_ON_DEPENDENCIES | Codex | workspace | needs PKT-LFC-012 VERIFIED + PKT-RLS-011 VERIFIED | 05, 33, 43, 48, 56, packet | 2026-04-02 | make clean-project install, existing-project refresh, and self-host bootstrap use the same managed baseline rules |

### Phase 2 — Release / Audit / Ledger / Release Please

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-RLS-001 | Record fragment per change event | VERIFIED | Codex | workspace | needs Phase 1 VERIFIED | 09, 13, packet | 2026-03-29 | tests: tests/unit/release/test_fragments.py |
| PKT-RLS-002 | Sync current release ledger with lock + manifest | VERIFIED | Codex | workspace | needs PKT-RLS-001 VERIFIED | 09, packet | 2026-03-29 | tests: tests/integration/release/test_sync.py |
| PKT-RLS-003 | Regenerate current release summary | VERIFIED | Codex | workspace | needs PKT-RLS-002 VERIFIED | 09, packet | 2026-03-29 | tests: tests/integration/release/test_current_summary.py |
| PKT-RLS-004 | Generate audit + check-in summaries | VERIFIED | Codex | workspace | needs PKT-RLS-002 + PKT-RLS-003 VERIFIED | 09, packet | 2026-03-29 | tests: tests/integration/release/test_audit_summary.py; fixtures: audit-summary.sample.md, checkin.sample.md |
| PKT-RLS-005 | Finalize release with exactly-once append | VERIFIED | Codex | workspace | needs PKT-RLS-002 + PKT-RLS-003 + PKT-RLS-004 VERIFIED | 09, 10, packet | 2026-03-29 | tests: tests/e2e/release/test_finalize.py; fixture: finalize-checkpoint.partial.json |
| PKT-RLS-006 | Release Please baseline workflow/config management | VERIFIED | Codex | workspace | needs PKT-LFC-003 + PKT-RLS-005 VERIFIED | 10, 23, packet | 2026-03-29 | tests: tests/integration/release/test_release_please_management.py; fixtures: release-please-*.sample.yml |
| PKT-RLS-007 | Convert legacy changelog/history to ledger events | VERIFIED | Codex | workspace | needs PKT-LFC-005 + PKT-RLS-001 VERIFIED | 09, 15, packet | 2026-03-29 | tests: tests/integration/release/test_history_import.py; fixture: legacy-changelog.sample.md |
| PKT-RLS-008 | End-to-end release flow integration tests | VERIFIED | Codex | workspace | needs all Phase 2 RLS packets VERIFIED | 24, packet | 2026-03-29 | tests: tests/integration/release/test_end_to_end_release_flow.py |

### Phase 2.1 — Incremental Release/Ledger Updates

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-RLS-009 | Release updates for new contract fields | VERIFIED | Codex | workspace | needs Phase 2 VERIFIED + PKT-FND-008 VERIFIED | 09, 10, packet | 2026-03-30 | release docs explicitly summarize or omit provider/model metadata |

### Phase 2.2 — Prompt / Review Release-Ledger Updates

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-RLS-010 | Release/audit handling for prompt and review metadata | VERIFIED | Codex | workspace | needs Phase 2 VERIFIED + PKT-FND-009 VERIFIED | 09, 10, 26, 35, packet | 2026-03-30 | omit raw prompt text/review bundles by default; allow deterministic summarized outcome handling |

### Phase 2.3 — Project Release Bootstrap and Workflow Activation

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-RLS-011 | Project release bootstrap and workflow activation | VERIFIED | Codex | workspace | needs Phase 2 VERIFIED + PKT-RLS-006 VERIFIED + PKT-RLS-008 VERIFIED + PKT-LFC-003 VERIFIED | 05, 09, 10, 23, packet | 2026-03-31 | bootstrap command installs project-local release workflow state, preserves existing provider config, and activates the project's own release machinery |

### Phase 3 — Jobs and Simple Workflows

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-JOB-001 | Job record store and state machine | VERIFIED | Codex | workspace | needs PKT-FND-002 + PKT-LFC-003 VERIFIED | 03, 05, packet | 2026-03-30 | tests: tests/unit/jobs/test_state_machine.py |
| PKT-JOB-002 | Workflow profile loader and validator | VERIFIED | Codex | workspace | needs PKT-FND-002 + PKT-JOB-001 VERIFIED | 03, 05, packet | 2026-03-30 | tests: tests/unit/jobs/test_profiles.py; fixtures: workflow-overrides.*.yaml |
| PKT-JOB-003 | Packet runner | VERIFIED | Codex | workspace | needs PKT-JOB-001 + PKT-JOB-002 VERIFIED | 03, 05, packet | 2026-03-30 | tests: tests/integration/jobs/test_packet_runner.py |
| PKT-JOB-004 | Stage execution contract + stage output persistence | VERIFIED | Codex | workspace | needs PKT-JOB-003 VERIFIED | 03, 05, packet | 2026-03-30 | tests: tests/unit/jobs/test_stage_contract.py; fixtures: stage-result.*.json; runner updated for stage persistence |
| PKT-JOB-005 | Approvals and timeouts inside jobs | VERIFIED | Codex | workspace | needs PKT-JOB-001 + PKT-JOB-004 VERIFIED | 03, 05, packet | 2026-03-30 | tests: tests/integration/jobs/test_job_approvals.py |
| PKT-JOB-006 | Release script integration from jobs | VERIFIED | Codex | workspace | needs PKT-JOB-003 + PKT-RLS-001/003/004 VERIFIED | 03, 05, packet | 2026-03-30 | tests: tests/integration/jobs/test_release_bridge.py |

### Phase 3.1 — Incremental Job Updates

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-JOB-007 | Job updates for provider model selection | VERIFIED | Codex | workspace | needs Phase 3 VERIFIED + PKT-FND-008 VERIFIED + PKT-PRV-012 VERIFIED (seam: job model selection consumes shared provider/model contract) | 08, 12, packet | 2026-03-30 | job fields: provider-id, model-id, model-alias, default-model |

### Phase 3.2 — Prompt-Tagged Workflow Launch and Review Loop

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-JOB-008 | Prompt-tagged launch core + ad hoc target | VERIFIED | Codex | workspace | needs Phase 3 VERIFIED + PKT-JOB-007 VERIFIED + PKT-FND-009 VERIFIED + PKT-LFC-009 VERIFIED | 08, 12, 26, 35, packet | 2026-03-30 | parser, normalized launch envelope, target legality, CLI/VS Code provenance; provider shorthand defaults and short tag aliases added; explicit `@adhoc` may remain feature-gated in pass 1 |
| PKT-JOB-009 | Structured review loop + multi-review aggregation | VERIFIED | Codex | workspace | needs PKT-JOB-008 VERIFIED + PKT-RLS-010 VERIFIED | 08, 12, 14, 26, 35, packet | 2026-03-30 | review reports, review bundle, all-pass aggregation, deterministic review-gated progression |

### Phase 3.3 — Prompt Shorthand and Default-Launch Enhancement

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-JOB-010 | Prompt shorthand and default-launch behavior | VERIFIED | Codex | workspace | needs PKT-JOB-008 VERIFIED + PKT-PRV-012 VERIFIED + PKT-PRV-013 VERIFIED (seam: shorthand defaults depend on provider catalog/status contracts) | 08, 12, 26, packet | 2026-03-30 | provider shorthand defaults, short tag aliases, default subject generation, provider-default model resolution |

### Phase 3.4 — Job Control and Running-Job Cancellation

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-JOB-011 | Job control and running-job cancellation | READY_FOR_REVIEW | Codex | workspace | needs PKT-JOB-001 + PKT-JOB-004 + PKT-JOB-005 + PKT-JOB-009 VERIFIED | 08, 12, 32, packet | 2026-03-30 | explicit stop/cancel surface for pending, awaiting-approval, and running jobs; control module, CLI, and tests added |

### Later phases

Later phases should continue this registry pattern using the same fields and status rules. Work may be listed now as `WAITING_ON_DEPENDENCIES`, but active claiming should not occur until earlier phase gates are closed.

### Phase 4 — Providers and Optional Server Foundation

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-PRV-001 | Provider registry and descriptor validation | VERIFIED | Codex | workspace | needs PKT-FND-001 + PKT-FND-002 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/unit/providers/test_registry.py |
| PKT-PRV-002 | Provider selection and health check service | VERIFIED | Codex | workspace | needs PKT-PRV-001 + PKT-JOB-003 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/integration/providers/test_selection.py; fixtures: provider-health.*.json |
| PKT-PRV-003 | local-openai provider adapter | VERIFIED | Codex | workspace | needs PKT-PRV-001 + PKT-PRV-002 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/integration/providers/test_local_openai.py |
| PKT-PRV-004 | claude provider adapter | VERIFIED | Codex | workspace | needs PKT-PRV-001 + PKT-PRV-002 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/integration/providers/test_claude.py; live wrapper smoke test verified; hook/skills assets still needed for full native-intercept rollout |
| PKT-PRV-005 | codex provider adapter | VERIFIED | Codex | workspace | needs PKT-PRV-001 + PKT-PRV-002 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/integration/providers/test_codex.py; live wrapper smoke test verified; prompt envelope still needs richer task payload for fully specific execution |
| PKT-PRV-006 | gemini provider adapter | VERIFIED | Codex | workspace | needs PKT-PRV-001 + PKT-PRV-002 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/integration/providers/test_gemini.py |
| PKT-PRV-007 | copilot provider adapter | VERIFIED | Codex | workspace | needs PKT-PRV-001 + PKT-PRV-002 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/integration/providers/test_copilot.py |
| PKT-PRV-008 | continue provider adapter | VERIFIED | Codex | workspace | needs PKT-PRV-001 + PKT-PRV-002 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/integration/providers/test_continue.py |
| PKT-PRV-009 | cline provider adapter | VERIFIED | Codex | workspace | needs PKT-PRV-001 + PKT-PRV-002 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/integration/providers/test_cline.py |
| PKT-PRV-010 | Job/provider integration seam tests | VERIFIED | Codex | workspace | needs PKT-PRV-002 + PKT-JOB-003 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/integration/providers/test_job_provider_seam.py |
| PKT-PRV-011 | Provider access-mode contract + health config rules | VERIFIED | Codex | workspace | needs PKT-PRV-002 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/unit/contracts/test_schema_validation.py; tests/integration/providers/test_selection.py; tests/integration/test_example_scaffold.py; tests/e2e/lifecycle/test_fresh_install.py |
| PKT-SRV-001 | Optional server seam foundation | VERIFIED | Codex | workspace | needs PKT-JOB-006 + PKT-PRV-002 VERIFIED | 03, 06, packet | 2026-03-30 | tests: tests/unit/server/test_service_boundary.py; fixture: server-seam.request.json |

### Phase 4.1 — Provider Model Catalog and Selection

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-PRV-012 | Provider model catalog + selection rules | VERIFIED | Codex | workspace | needs PKT-PRV-011 VERIFIED | 03, 24, packet | 2026-03-30 | adds model catalog contract, schema, CLI refresh, aliases, default-model resolution |

### Phase 4.2 — Provider Status and Validation

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-PRV-013 | Provider CLI/status inspection | VERIFIED | Codex | workspace | needs PKT-PRV-012 VERIFIED | 03, 24, packet | 2026-03-30 | status command reports config health, CLI availability, and catalog presence |

### Phase 4.3 — Provider Prompt-Tag Surface Integration

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-PRV-014 | Shared prompt-tag surface contract + sync harness | VERIFIED | Codex | workspace | needs PKT-PRV-012 VERIFIED + PKT-FND-009 VERIFIED + PKT-LFC-009 VERIFIED + PKT-RLS-010 VERIFIED + PKT-JOB-008 VERIFIED + PKT-JOB-009 VERIFIED | 03, 27, 38, packet | 2026-03-30 | shared prompt-surface config/descriptor fields and sync harness |
| PKT-PRV-015 | codex prompt-tag surface integration | READY_TO_START | Codex | workspace | needs PKT-PRV-014 VERIFIED + PKT-PRV-005 VERIFIED | 03, 27, 38, packet | 2026-03-30 | codex wrapper/extension prompt-tag rollout |
| PKT-PRV-016 | claude prompt-tag surface integration | READY_TO_START | Codex | workspace | needs PKT-PRV-014 VERIFIED + PKT-PRV-004 VERIFIED | 03, 27, 38, packet | 2026-03-30 | claude wrapper/extension prompt-tag rollout |
| PKT-PRV-017 | gemini prompt-tag surface integration | READY_FOR_REVIEW | Gemini CLI | workspace | needs PKT-PRV-014 VERIFIED + PKT-PRV-006 VERIFIED | 03, 27, 38, packet | 2026-03-30 | implemented prompt-tag detection and normalization; smoke tests simulated |
| PKT-PRV-018 | copilot prompt-tag surface integration | READY_TO_START | Codex | workspace | needs PKT-PRV-014 VERIFIED + PKT-PRV-007 VERIFIED | 03, 27, 38, packet | 2026-03-30 | copilot surface rollout |
| PKT-PRV-019 | continue prompt-tag surface integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-014 VERIFIED + PKT-PRV-008 VERIFIED | 03, 27, 38, packet | 2026-03-30 | future integration; not part of the active prompt-calling rollout |
| PKT-PRV-020 | cline prompt-tag surface integration | READY_TO_START | Codex | workspace | needs PKT-PRV-014 VERIFIED + PKT-PRV-009 VERIFIED | 03, 27, 38, packet | 2026-03-30 | cline wrapper/extension prompt-tag rollout |
| PKT-PRV-021 | local-openai/qwen bridge-wrapper prompt-tag integration | VERIFIED | Codex | workspace | needs PKT-PRV-014 VERIFIED + PKT-PRV-003 VERIFIED + PKT-PRV-011 VERIFIED | 03, 27, 38, packet | 2026-03-30 | bridge-wrapper surface wiring for local-openai and qwen; bridge wrappers and smoke tests are implemented |

### Phase 4.4 — Provider Tag Execution Compliance and Isolated Provider Implementations

| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-PRV-022 | Provider tag execution compliance model + conformance matrix | VERIFIED | Codex | workspace | needs PKT-PRV-014 VERIFIED + PKT-PRV-012 VERIFIED + PKT-PRV-013 VERIFIED | 03, 27, 28, 39, packet | 2026-03-30 | shared provider execution compliance model and matrix |
| PKT-PRV-023 | Codex tag execution implementation | READY_TO_START | Codex | workspace | needs PKT-PRV-022 VERIFIED + PKT-PRV-005 VERIFIED | 28, 39, packet | 2026-03-30 | isolated Codex execution doc and smoke-test guidance |
| PKT-PRV-024 | Claude Code tag execution implementation | READY_TO_START | Codex | workspace | needs PKT-PRV-022 VERIFIED + PKT-PRV-004 VERIFIED | 28, 39, packet | 2026-03-30 | isolated Claude execution doc and smoke-test guidance |
| PKT-PRV-025 | Gemini tag execution implementation | READY_FOR_REVIEW | Gemini CLI | workspace | needs PKT-PRV-022 VERIFIED + PKT-PRV-006 VERIFIED | 28, 39, packet | 2026-03-30 | implemented native intercept guidance and GEMINI.md |
| PKT-PRV-026 | GitHub Copilot tag execution implementation | READY_TO_START | Codex | workspace | needs PKT-PRV-022 VERIFIED + PKT-PRV-007 VERIFIED | 28, 39, packet | 2026-03-30 | isolated Copilot execution doc and smoke-test guidance |
| PKT-PRV-027 | Continue tag execution implementation | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-022 VERIFIED + PKT-PRV-008 VERIFIED | 28, 39, packet | 2026-03-30 | future integration; isolated Continue execution doc and smoke-test guidance are deferred |
| PKT-PRV-028 | Cline tag execution implementation | VERIFIED | Codex | workspace | needs PKT-PRV-022 VERIFIED + PKT-PRV-009 VERIFIED | 28, 39, packet | 2026-03-30 | CLI-backed wrapper implemented and smoke-tested; hook-native path remains feature-gated |
| PKT-PRV-029 | local OpenAI-compatible tag execution implementation | READY_TO_START | Codex | workspace | needs PKT-PRV-022 VERIFIED + PKT-PRV-003 VERIFIED + PKT-PRV-011 VERIFIED | 28, 39, packet | 2026-03-30 | backend-only provider execution doc and smoke-test guidance |
| PKT-PRV-030 | Qwen Code tag execution implementation | VERIFIED | Codex | workspace | needs PKT-PRV-022 VERIFIED + PKT-PRV-003 VERIFIED + PKT-PRV-011 VERIFIED | 28, 39, packet | 2026-03-30 | CLI-backed wrapper implemented and smoke-tested; hook-native path remains feature-gated |

### Phase 4.6 — Provider Prompt-Trigger Launch Behavior

| Packet | Title | Status | Owner | Scope | Dependencies | Docs | Updated | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-PRV-031 | Shared provider prompt-trigger launch contract + bridge harness | VERIFIED | Codex | workspace | needs PKT-PRV-014 VERIFIED + PKT-JOB-008 VERIFIED + PKT-JOB-009 VERIFIED | 03, 29, 40, packet | 2026-03-30 | canonical trigger grammar, launcher bridge, and fallback wrapper contract; shared bridge harness implemented and tested |
| PKT-PRV-032 | Codex prompt-trigger launch integration | READY_FOR_REVIEW | Codex | workspace | needs PKT-PRV-031 VERIFIED + PKT-PRV-005 VERIFIED | 03, 29, 40, packet | 2026-03-30 | AGENTS.md / wrapper path for Codex prompt-trigger launch; Codex repo guidance and wrapper bridge are implemented |
| PKT-PRV-033 | Claude prompt-trigger launch integration (Option A baseline) | VERIFIED | Codex | workspace | needs PKT-PRV-031 READY_FOR_REVIEW + PKT-PRV-004 VERIFIED | 03, 20, 29, 40, packet | 2026-04-02 | Option A wrapper baseline complete: .claude/skills/{plan,implement,review,audit,check-in-prep}/SKILL.md + REQUIRED_ASSETS validation + uses shared default prompts (provider-specific only when constrained, like Cline's read-only review) + tests passing; Option B native hook integration ready to start (PKT-PRV-055) |
| PKT-PRV-034 | Gemini prompt-trigger launch integration | READY_FOR_REVIEW | Codex | workspace | needs PKT-PRV-031 VERIFIED + PKT-PRV-006 VERIFIED | 03, 29, 40, packet | 2026-03-30 | Gemini instruction surface and wrapper path for prompt-trigger launch; Gemini repo guidance and wrapper bridge are implemented |
| PKT-PRV-035 | GitHub Copilot prompt-trigger launch integration | READY_FOR_REVIEW | Codex | workspace | needs PKT-PRV-031 VERIFIED + PKT-PRV-007 VERIFIED | 03, 29, 40, packet | 2026-03-30 | Copilot config / instruction surface and bridge path for prompt-trigger launch; repo-local Copilot bridge assets and wrapper path are implemented |
| PKT-PRV-036 | Continue prompt-trigger launch integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-031 DEFERRED_DRAFT + PKT-PRV-008 VERIFIED | 03, 29, 40, packet | 2026-03-30 | future integration; Continue config surface and wrapper path for prompt-trigger launch |
| PKT-PRV-037 | Cline prompt-trigger launch integration | READY_FOR_REVIEW | Codex | workspace | needs PKT-PRV-031 READY_FOR_REVIEW + PKT-PRV-009 VERIFIED | 03, 29, 40, packet | 2026-03-30 | Cline rule/hook surface and wrapper path for prompt-trigger launch; Cline repo guidance and wrapper bridge are implemented |
| PKT-PRV-038 | local-openai/qwen prompt-trigger bridge integration | READY_FOR_REVIEW | Codex | workspace | needs PKT-PRV-031 VERIFIED + PKT-PRV-003 VERIFIED + PKT-PRV-011 VERIFIED | 03, 29, 40, packet | 2026-03-30 | bridge-owned launch path for backend-only surfaces; local-openai and Qwen bridge wrappers are implemented |
| PKT-PRV-055 | Claude UserPromptSubmit and PreToolUse native hook integration (Option B) | VERIFIED | Claude | workspace | needs PKT-PRV-033 VERIFIED | 20, 33, 45, packet | 2026-04-02 | Option B native hook path complete: .claude/settings.json hook config + tools/claude_hooks.py handlers + stage restrictions + tests passing; Option A and B now form complete Claude baseline path |

### Phase 4.7 — Provider Availability and Auto-Install Orchestration

| Packet | Title | Status | Owner | Scope | Dependencies | Docs | Updated | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-PRV-039 | Shared provider availability and auto-install contract + bootstrap harness | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-012 VERIFIED + PKT-PRV-013 VERIFIED + PKT-PRV-031 DEFERRED_DRAFT | 03, 30, 41, packet | 2026-03-30 | shared install policy, availability probe, and bootstrap harness |
| PKT-PRV-040 | Codex auto-install integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-039 DEFERRED_DRAFT + PKT-PRV-005 VERIFIED + PKT-PRV-015 READY_TO_START | 03, 30, 41, packet | 2026-03-30 | Codex install/bootstrap guidance and smoke tests |
| PKT-PRV-041 | Claude auto-install integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-039 DEFERRED_DRAFT + PKT-PRV-004 VERIFIED + PKT-PRV-016 READY_TO_START | 03, 30, 41, packet | 2026-03-30 | Claude install/bootstrap guidance and smoke tests |
| PKT-PRV-042 | Gemini auto-install integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-039 DEFERRED_DRAFT + PKT-PRV-006 VERIFIED + PKT-PRV-017 IN_PROGRESS | 03, 30, 41, packet | 2026-03-30 | Gemini install/bootstrap guidance and smoke tests |
| PKT-PRV-043 | GitHub Copilot auto-install integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-039 DEFERRED_DRAFT + PKT-PRV-007 VERIFIED + PKT-PRV-018 READY_TO_START | 03, 30, 41, packet | 2026-03-30 | Copilot install/bootstrap guidance and smoke tests |
| PKT-PRV-044 | Continue auto-install integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-039 DEFERRED_DRAFT + PKT-PRV-008 VERIFIED + PKT-PRV-019 DEFERRED_DRAFT | 03, 30, 41, packet | 2026-03-30 | future integration; Continue install/bootstrap guidance and smoke tests are deferred |
| PKT-PRV-045 | Cline auto-install integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-039 DEFERRED_DRAFT + PKT-PRV-009 VERIFIED + PKT-PRV-020 READY_TO_START | 03, 30, 41, packet | 2026-03-30 | Cline install/bootstrap guidance and smoke tests |
| PKT-PRV-046 | local-openai availability and bridge bootstrap | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-039 DEFERRED_DRAFT + PKT-PRV-003 VERIFIED + PKT-PRV-021 VERIFIED | 03, 30, 41, packet | 2026-03-30 | bridge-owned availability and bootstrap for backend-only surfaces |
| PKT-PRV-047 | Qwen auto-install integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-039 DEFERRED_DRAFT + PKT-PRV-030 VERIFIED + PKT-PRV-021 VERIFIED | 03, 30, 41, packet | 2026-03-30 | Qwen install/bootstrap guidance and smoke tests |

### Phase 4.9 — Provider Live Stream and Progress Capture

| Packet | Title | Status | Owner | Scope | Dependencies | Docs | Updated | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-PRV-048 | Shared provider live-stream capture contract + harness | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-031 VERIFIED + PKT-PRV-022 VERIFIED | 03, 34, 45, packet | 2026-03-31 | shared live-stream event contract, stdout/stderr capture helpers, normalized runtime records, and console mirroring switches |
| PKT-PRV-049 | Codex live-stream capture integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-048 DEFERRED_DRAFT + PKT-PRV-005 VERIFIED + PKT-PRV-032 READY_FOR_REVIEW | 03, 34, 45, packet | 2026-03-31 | Codex is the first-wave validation provider for live console capture and runtime persistence |
| PKT-PRV-050 | Cline live-stream capture integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-048 DEFERRED_DRAFT + PKT-PRV-009 VERIFIED + PKT-PRV-037 READY_FOR_REVIEW | 03, 34, 45, packet | 2026-03-31 | Cline is the first-wave validation provider for live console capture and runtime persistence |

### Phase 4.10 — Provider Live Input and Interactive Session Control

| Packet | Title | Status | Owner | Scope | Dependencies | Docs | Updated | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-PRV-051 | Shared provider live-input capture contract + harness | READY_FOR_REVIEW | Codex | workspace | needs PKT-PRV-048 DEFERRED_DRAFT + PKT-PRV-031 VERIFIED + PKT-PRV-022 VERIFIED | 03, 35, 46, packet | 2026-03-31 | shared input event contract, stdin forwarding helpers, normalized runtime input records, and console input switches; harness implemented and test-covered |
| PKT-PRV-052 | Codex live-input capture integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-051 READY_FOR_REVIEW + PKT-PRV-005 VERIFIED + PKT-PRV-032 READY_FOR_REVIEW | 03, 35, 46, packet | 2026-03-31 | Codex is the first-wave validation provider for live interactive input and runtime persistence |
| PKT-PRV-053 | Cline live-input capture integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-051 READY_FOR_REVIEW + PKT-PRV-009 VERIFIED + PKT-PRV-037 READY_FOR_REVIEW | 03, 35, 46, packet | 2026-03-31 | Cline is the first-wave validation provider for live interactive input and runtime persistence |
| PKT-PRV-054 | Session provenance redaction and secure-session reference seam | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-051 READY_FOR_REVIEW + Phase 4.10 IN_PROGRESS | 03, 35, 46, packet | 2026-04-02 | capture the rule that raw provider session keys are not log-safe; durable runtime artifacts may keep only redacted handles or secure references until a fuller secure-session store is defined |

### Phase 4.11 — Provider Structured Completion and Result Normalization

| Packet | Title | Status | Owner | Scope | Dependencies | Docs | Updated | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-PRV-056 | Shared provider structured-completion contract + normalization harness | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-048 DEFERRED_DRAFT + PKT-PRV-051 READY_FOR_REVIEW + PKT-PRV-031 VERIFIED | 03, 36, 47, packet | 2026-04-02 | shared final-result contract, direct-vs-fallback result marking, canonical completion persistence, and shared normalization fixtures/tests |
| PKT-PRV-057 | Codex structured-completion integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-056 DEFERRED_DRAFT + PKT-PRV-005 VERIFIED + PKT-PRV-032 READY_FOR_REVIEW | 03, 36, 47, packet | 2026-04-02 | Codex uses wrapper-first completion with final-message/result-file normalization into the shared result envelope |
| PKT-PRV-058 | Cline structured-completion integration | DEFERRED_DRAFT | Codex | workspace | needs PKT-PRV-056 DEFERRED_DRAFT + PKT-PRV-009 VERIFIED + PKT-PRV-037 READY_FOR_REVIEW | 03, 36, 47, packet | 2026-04-02 | Cline uses stdout/NDJSON completion normalization into the shared result envelope and should eliminate synthetic review fallback when parsing succeeds |
| PKT-PRV-059 | Centralized prompt syntax and combined alias configuration | VERIFIED | Infrastructure | workspace | needs PKT-PRV-031 VERIFIED + prompt parser already in place | 03, 46, packet | 2026-04-02 | .audiagentic/prompt-syntax.yaml now includes combined-aliases (e.g., @r-cln for @review provider=cline); all 18 tag+provider shortcuts defined; hook handlers simplified to delegate normalization to shared bridge; no code changes needed for new aliases |
| PKT-PRV-060 | Provider prompt template architecture and defaults | VERIFIED | Infrastructure | workspace | needs PKT-PRV-031 VERIFIED + template loader already in place | 03, 47, packet | 2026-04-02 | shared defaults for all action types; provider-specific variants only when materially justified (read-only constraints, format differences, framework expectations); Cline review variant kept, unnecessary Claude templates removed; DRY principle + guidance for future providers |

### Phase 4.12 — Provider Optimization and Shared Workflow Extensibility

| Packet | Title | Status | Owner | Scope | Dependencies | Docs | Updated | Notes |
|---|---|---|---|---|---|---|---|---|
| Phase 4.12 | docs-only draft | DEFERRED_DRAFT | Codex | workspace | needs Phase 4.11 DEFERRED_DRAFT + future workflow model definition | 03, 37, 48, providers/32 | 2026-03-31 | shared optimization hooks and workflow tracker extension points are documented; repeatable operations are script-first and template-driven; implementation is intentionally deferred until the workflow model is defined |

### Phase 7 — Node Execution and Federation Extension

| Packet | Title | Status | Owner | Scope | Dependencies | Docs | Updated | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-NOD-001 | Node descriptor and identity module | WAITING_ON_DEPENDENCIES | Codex | workspace | needs current Phase 4 active provider/runtime work stabilized + Phase 7 docs in place | 03, 38, 39, packet | 2026-04-01 | node identity and runtime helpers are additive future work |
| PKT-NOD-002 | Node heartbeat and status persistence | WAITING_ON_DEPENDENCIES | Codex | workspace | needs PKT-NOD-001 READY_TO_START + Phase 7 docs in place | 03, 38, 41, packet | 2026-04-01 | node heartbeat/status persistence is additive future work |
| PKT-NOD-003 | Node-aware job ownership fields | WAITING_ON_DEPENDENCIES | Codex | workspace | needs PKT-NOD-001 READY_TO_START + PKT-JOB-001 VERIFIED + PKT-JOB-011 VERIFIED | 03, 38, 39, packet | 2026-04-01 | additive job ownership fields are future work and must not alter single-node behavior |

### Phase 8 — Discovery and Registry Extension

| Packet | Title | Status | Owner | Scope | Dependencies | Docs | Updated | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-DIS-001 | Locator provider contract and static registry provider | WAITING_ON_DEPENDENCIES | Codex | workspace | needs Phase 7 VERIFIED + Phase 8 docs in place | 03, 40, 50, packet | 2026-04-01 | static registry is the first additive discovery backend |
| PKT-DIS-002 | Zeroconf locator provider (optional) | WAITING_ON_DEPENDENCIES | Codex | workspace | needs PKT-DIS-001 READY_TO_START + explicit operator opt-in | 03, 40, 50, packet | 2026-04-01 | optional same-subnet discovery remains disabled by default |
| PKT-DIS-003 | External registry provider seam | WAITING_ON_DEPENDENCIES | Codex | workspace | needs PKT-DIS-001 READY_TO_START | 03, 40, 50, packet | 2026-04-01 | external registry seams stay optional and replaceable |

### Phase 9 — Distributed Eventing and Control Extension

| Packet | Title | Status | Owner | Scope | Dependencies | Docs | Updated | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-EVT-001 | Node event families and publisher extension | WAITING_ON_DEPENDENCIES | Codex | workspace | needs Phase 7 VERIFIED + Phase 8 VERIFIED + Phase 9 docs in place | 03, 41, 51, packet | 2026-04-01 | local-first node event publication is future work |
| PKT-EVT-002 | Node control request contract | WAITING_ON_DEPENDENCIES | Codex | workspace | needs PKT-EVT-001 READY_TO_START + node identity/ownership fields implemented | 03, 41, 51, packet | 2026-04-01 | node-side drain/resume/quarantine/assign/release controls are future work |

### Phase 10 — Coordinator Consumption Seam

| Packet | Title | Status | Owner | Scope | Dependencies | Docs | Updated | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-CRD-001 | Coordinator consumption seam | WAITING_ON_DEPENDENCIES | Codex | workspace | needs Phase 9 VERIFIED + Phase 10 docs in place | 03, 42, 52, packet | 2026-04-01 | coordinator-facing queries and delegated requests are backend-only future seams |

### Phase 11 — Pluggable External Tool Connectivity

| Packet | Title | Status | Owner | Scope | Dependencies | Docs | Updated | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-EXT-001 | External tool/task-system connector contract | DEFERRED_DRAFT | Codex | workspace | needs Phase 10 VERIFIED + Phase 11 docs in place | 03, 43, 53, packet | 2026-04-01 | external connectors are later optional integrations and never the source of truth |

### Later phases

Later phases should continue this registry pattern using the same fields and status rules. Work may be listed now as `WAITING_ON_DEPENDENCIES`, but active claiming should not occur until earlier phase gates are closed.

| Phase | Packets | Current State |
|---|---|---|
| Phase 4.1 | PKT-PRV-012 | VERIFIED |
| Phase 4.2 | PKT-PRV-013 | VERIFIED |
| Phase 4.3 | PKT-PRV-014 .. PKT-PRV-021 | VERIFIED |
| Phase 4.4 | PKT-PRV-022 .. PKT-PRV-030 | VERIFIED |
| Phase 4.6 | PKT-PRV-031 .. PKT-PRV-038 | IN_PROGRESS |
| Phase 4.7 | PKT-PRV-039 .. PKT-PRV-047 | DEFERRED_DRAFT |
| Phase 4.9 | PKT-PRV-048 .. PKT-PRV-050 | DEFERRED_DRAFT |
| Phase 4.10 | PKT-PRV-051 .. PKT-PRV-054 | IN_PROGRESS |
| Phase 4.11 | PKT-PRV-056 .. PKT-PRV-058 | DEFERRED_DRAFT |
| Phase 4.12 | — | DEFERRED_DRAFT |
| Phase 4.13 | — | DEFERRED_DRAFT |
| Phase 7 | PKT-NOD-001 .. PKT-NOD-003 | WAITING_ON_DEPENDENCIES |
| Phase 8 | PKT-DIS-001 .. PKT-DIS-003 | WAITING_ON_DEPENDENCIES |
| Phase 9 | PKT-EVT-001 .. PKT-EVT-002 | WAITING_ON_DEPENDENCIES |
| Phase 10 | PKT-CRD-001 | WAITING_ON_DEPENDENCIES |
| Phase 11 | PKT-EXT-001 | DEFERRED_DRAFT |
| Phase 0.2 | PKT-FND-009 | VERIFIED |
| Phase 1.2 | PKT-LFC-009 | VERIFIED |
| Phase 2.2 | PKT-RLS-010 | VERIFIED |
| Phase 2.3 | PKT-RLS-011 | VERIFIED |
| Phase 3.2 | PKT-JOB-008, PKT-JOB-009 | VERIFIED | `@adhoc` is a conscious launch-scope choice, not an unresolved design gap |
| Phase 3.3 | PKT-JOB-010 | VERIFIED | prompt shorthand/default-launch enhancement complete |
| Phase 5 | PKT-DSC-001 .. PKT-DSC-004 | READY_TO_START |
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
