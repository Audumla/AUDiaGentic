---
id: task-0008-output
label: Migration Reference Map
state: done
summary: Complete inventory and reference map for all implementation docs
spec_ref: spec-0036
---


# Description

Reference map for all implementation docs.

# Implementation Docs Reference Map

**Generated:** 2026-04-08  
**Task:** task-0008 - Inventory all implementation docs and build reference map

## Summary

- **Total files:** 234 markdown files
- **Root docs:** 67 files in `docs/implementation/`
- **Packet docs:** 154 files in `docs/implementation/packets/*/`
- **Provider docs:** 37 files in `docs/implementation/providers/`
- **Refactor docs:** 11 files in `docs/implementation/refactor/*/`

## File Inventory

### Root Implementation Docs (67 files)

| # | File | Type | Phase |
|---|------|------|-------|
| 1 | 00_Implementation_Index.md | Index | All |
| 2 | 01_Master_Implementation_Roadmap.md | Roadmap | All |
| 3 | 02_Phase_0_Contracts_and_Scaffolding.md | Phase 0 | 0 |
| 4 | 02_Phase_Gates_and_Exit_Criteria.md | Gates | All |
| 5 | 03_Phase_1_Lifecycle_and_Project_Enablement.md | Phase 1 | 1 |
| 6 | 03_Target_Codebase_Tree.md | Target | All |
| 7 | 04_Phase_2_Release_Audit_Ledger_and_Release_Please.md | Phase 2 | 2 |
| 8 | 04_System_Assembly_Sequence.md | Assembly | All |
| 9 | 05_Module_Ownership_and_Parallelization_Map.md | Ownership | All |
| 10 | 05_Phase_3_Agent_Jobs_and_Simple_Workflows.md | Phase 3 | 3 |
| 11 | 06_Phase_0_Build_Book.md | Build Book | 0 |
| 12 | 06_Phase_4_Providers_and_Optional_Server_Foundation.md | Phase 4 | 4 |
| 13 | 07_Phase_1_Build_Book.md | Build Book | 1 |
| 14 | 07_Phase_5_Discord_Overlay.md | Phase 5 | 5 |
| 15 | 08_Phase_2_Build_Book.md | Build Book | 2 |
| 16 | 08_Phase_6_Migration_and_Cutover_Completion.md | Phase 6 | 6 |
| 17 | 09_Module_Ownership_and_Parallelization_Map.md | Ownership | All |
| 18 | 09_Phase_3_Build_Book.md | Build Book | 3 |
| 19 | 10_Executable_Packets_Foundation_and_Contracts.md | Packets | All |
| 20 | 10_Phase_4_Build_Book.md | Build Book | 4 |
| 21 | 11_Executable_Packets_Lifecycle.md | Packets | 1 |
| 22 | 11_Phase_4_1_Provider_Model_Catalog_and_Selection.md | Phase 4.1 | 4 |
| 23 | 11_Phase_5_Build_Book.md | Build Book | 5 |
| 24 | 12_Executable_Packets_Release_and_Ledger.md | Packets | 2 |
| 25 | 12_Phase_6_Build_Book.md | Build Book | 6 |
| 26 | 13_Executable_Packets_Jobs_and_Workflows.md | Packets | 3 |
| 27 | 13_Packet_Execution_Rules.md | Rules | All |
| 28 | 14_End_to_End_Staged_Build_Summary.md | Summary | All |
| 29 | 14_Executable_Packets_Providers_and_Optional_Server.md | Packets | 4 |
| 30 | 15_Executable_Packets_Discord_and_Migration.md | Packets | 5-6 |
| 31 | 16_Acceptance_Matrix_and_Destructive_Test_Cases.md | Tests | All |
| 32 | 17_Current_State_and_Action_Summary.md | Status | All |
| 33 | 18_Review_Resolution_and_Preimplementation_Gates.md | Gates | All |
| 34 | 19_CI_CD_and_Testing_Infrastructure.md | Infrastructure | 0 |
| 35 | 20_Packet_Dependency_Graph.md | Dependencies | All |
| 36 | 21_Destructive_Test_Sandbox.md | Tests | All |
| 37 | 22_Secret_Management.md | Infrastructure | All |
| 38 | 23_Release_Please_Invocation.md | Infrastructure | 2 |
| 39 | 24_Cross_Phase_Integration_Testing.md | Tests | All |
| 40 | 25_Change_Control_and_Document_Update_Rules.md | Rules | All |
| 41 | 26_DRAFT_Migration_Runbooks.md | Draft | All |
| 42 | 27_Phase_0_Kickoff_Checklist.md | Checklist | 0 |
| 43 | 28_DRAFT_Platform_Compatibility_and_Portability.md | Draft | All |
| 44 | 29_DRAFT_Performance_and_Scale_Guidance.md | Draft | All |
| 45 | 30_DRAFT_Developer_Onboarding.md | Draft | All |
| 46 | 31_Build_Status_and_Work_Registry.md | Registry | All |
| 47 | 32_New_Agent_or_Developer_Start_Here.md | Onboarding | All |
| 48 | 33_Phase_0_1_2_Readiness_and_Execution_Reference.md | Reference | 0-2 |
| 49 | 34_DRAFT_Prompt_Tagged_Workflow_Launch_and_Review_Loop.md | Draft | 3 |
| 50 | 35_Phase_3_2_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md | Phase 3.2 | 3 |
| 51 | 36_Prompt_Extension_Readiness_Assessment.md | Assessment | 3 |
| 52 | 37_Phase_3_3_Prompt_Tagged_Workflow_Shortcuts_and_Defaults.md | Phase 3.3 | 3 |
| 53 | 38_Phase_4_3_Provider_Prompt_Tag_Surface_Integration.md | Phase 4.3 | 4 |
| 54 | 39_Phase_4_4_Provider_Tag_Execution_Implementation.md | Phase 4.4 | 4 |
| 55 | 40_Phase_4_6_Provider_Prompt_Trigger_Launch_Behavior.md | Phase 4.6 | 4 |
| 56 | 41_Phase_4_7_Provider_Auto_Install_Orchestration.md | Phase 4.7 | 4 |
| 57 | 42_Phase_3_4_Job_Control_and_Running_Job_Cancellation.md | Phase 3.4 | 3 |
| 58 | 43_Phase_2_3_Project_Release_Bootstrap_and_Workflow_Activation.md | Phase 2.3 | 2 |
| 59 | 45_Phase_4_9_Provider_Live_Stream_and_Progress_Capture.md | Phase 4.9 | 4 |
| 60 | 46_Phase_4_10_Provider_Live_Input_and_Interactive_Session_Control.md | Phase 4.10 | 4 |
| 61 | 47_Phase_4_11_Provider_Structured_Completion_and_Result_Normalization.md | Phase 4.11 | 4 |
| 62 | 48_Phase_4_12_Provider_Optimization_and_Shared_Workflow_Extensibility.md | Phase 4.12 | 4 |
| 63 | 49_Phase_7_Node_Execution_Extension_Build_Book.md | Phase 7 | 7 |
| 64 | 50_Phase_8_Discovery_and_Registry_Extension_Build_Book.md | Phase 8 | 8 |
| 65 | 51_Phase_9_Distributed_Eventing_and_Control_Extension_Build_Book.md | Phase 9 | 9 |
| 66 | 52_Phase_10_Coordinator_Consumption_Seam_Build_Book.md | Phase 10 | 10 |
| 67 | 53_Phase_11_Pluggable_External_Tool_Connectivity_Build_Book.md | Phase 11 | 11 |
| 68 | 54_Build_Status_Registry_Extension_For_Phases_7_11.md | Extension | 7-11 |
| 69 | 55_Phase_4_13_Canonical_Prompt_Entry_and_Bridge_End_State.md | Phase 4.13 | 4 |
| 70 | 56_Phase_1_4_Installable_Project_Baseline_and_Managed_Asset_Synchronization.md | Phase 1.4 | 1 |
| 71 | 56_Phase_4_Remaining_Work_Execution_Guide.md | Phase 4 | 4 |
| 72 | 57_Phase_0_3_Repository_Domain_Refactor_and_Package_Realignment.md | Phase 0.3 | 0 |
| 73 | CLAUDE_OPTION_A_B_SUMMARY.md | Summary | 4 |
| 74 | phase-4-cli-testing-summary.md | Testing | 4 |
| 75 | provider-status-report.md | Status | 4 |
| 76 | tag-routing-full-test-report.md | Testing | All |
| 77 | tag-routing-test-report.md | Testing | All |

### Packet Docs by Phase (154 files)

#### Phase 0 - Contracts and Scaffolding (13 files)
- [PKT-FND-001](task-0032).md through [PKT-FND-013](task-0044).md

#### Phase 1 - Lifecycle (13 files)
- [PKT-LFC-001](task-0045).md through [PKT-LFC-013](task-0055).md

#### Phase 2 - Release (11 files)
- [PKT-RLS-001](task-0056).md through [PKT-RLS-011](task-0066).md

#### Phase 3 - Jobs (11 files)
- [PKT-JOB-001](task-0067).md through [PKT-JOB-011](task-0077).md

#### Phase 4 - Providers (78 files)
- [PKT-PRV-001](task-0078).md through [PKT-PRV-078](task-0156).md (includes [PKT-SRV-001](task-0157))

#### Phase 5 - Discord (4 files)
- [PKT-DSC-001](task-0158).md through [PKT-DSC-004](task-0161).md

#### Phase 6 - Migration (3 files)
- [PKT-MIG-001](task-0162).md through [PKT-MIG-003](task-0164).md

#### Phase 7 - Node Execution (3 files)
- [PKT-NOD-001](task-0165).md through [PKT-NOD-003](task-0167).md

#### Phase 8 - Discovery (3 files)
- [PKT-DIS-001](task-0168).md through [PKT-DIS-003](task-0170).md

#### Phase 9 - Eventing (2 files)
- [PKT-EVT-001](task-0171).md through [PKT-EVT-002](task-0172).md

#### Phase 10 - Coordinator (1 file)
- [PKT-CRD-001](task-0173).md

#### Phase 11 - External Tools (1 file)
- [PKT-EXT-001](task-0174).md

### Provider Plans (19 files)
- 01_Local_OpenAI_Compatible_Plan.md through 19_Qwen_Tag_Execution_Implementation.md

### Provider Runbooks (9 files)
- 20_Claude_Prompt_Trigger_Runbook.md through 28_Opencode_Prompt_Trigger_Runbook.md

### Provider Assessments (5 files)
- 29_Provider_Live_Stream_Progress_Capture_Assessment.md through 32_Provider_Optimization_and_Shared_Workflow_Extensibility_Matrix.md

### Provider Implementation Guides (8 files)
- 33_Claude_Native_Hook_Runbook.md through 35_Claude_Option_B_Implementation_Guide.md

### Refactor Phase 0.3 (11 files)
- ambiguity-report.md through session-input-adapter-decision.md

## Reference Analysis

### Root Files (Entry Points)

These files have no incoming references and should be migrated first:

1. **00_Implementation_Index.md** - Main entry point
2. **01_Master_Implementation_Roadmap.md** - Complete build sequence
3. **02_Phase_Gates_and_Exit_Criteria.md** - Phase gate definitions
4. **03_Target_Codebase_Tree.md** - Target structure
5. **04_System_Assembly_Sequence.md** - Assembly order
6. **05_Module_Ownership_and_Parallelization_Map.md** - Ownership map
7. **13_Packet_Execution_Rules.md** - Execution rules
8. **14_End_to_End_Staged_Build_Summary.md** - Build summary
9. **17_Current_State_and_Action_Summary.md** - Current status
10. **18_Review_Resolution_and_Preimplementation_Gates.md** - Review gates
11. **20_Packet_Dependency_Graph.md** - Dependency graph
12. **25_Change_Control_and_Document_Update_Rules.md** - Change rules
13. **31_Build_Status_and_Work_Registry.md** - Status registry
14. **32_New_Agent_or_Developer_Start_Here.md** - Onboarding

### Migration Order Recommendation

Based on dependency analysis, migrate in this order:

#### Phase 1: Foundation (No dependencies)
1. 00_Implementation_Index.md → plan-0002 (already done)
2. 01_Master_Implementation_Roadmap.md → plan-0003 (already done)
3. 02_Phase_Gates_and_Exit_Criteria.md → spec-000X
4. 03_Target_Codebase_Tree.md → spec-000X
5. 04_System_Assembly_Sequence.md → spec-000X
6. 05_Module_Ownership_and_Parallelization_Map.md → spec-000X
7. 13_Packet_Execution_Rules.md → spec-000X
8. 14_End_to_End_Staged_Build_Summary.md → plan-000X
9. 20_Packet_Dependency_Graph.md → spec-000X
10. 25_Change_Control_and_Document_Update_Rules.md → spec-000X
11. 31_Build_Status_and_Work_Registry.md → spec-000X
12. 32_New_Agent_or_Developer_Start_Here.md → spec-000X

#### Phase 2: Phase 0 Docs
- 02_Phase_0_Contracts_and_Scaffolding.md
- 06_Phase_0_Build_Book.md
- 10_Executable_Packets_Foundation_and_Contracts.md
- 11_Executable_Packets_Lifecycle.md
- 19_CI_CD_and_Testing_Infrastructure.md
- 21_Destructive_Test_Sandbox.md
- 22_Secret_Management.md
- 27_Phase_0_Kickoff_Checklist.md
- 33_Phase_0_1_2_Readiness_and_Execution_Reference.md
- [PKT-FND-001](task-0032).md through [PKT-FND-013](task-0044).md

#### Phase 3: Phase 1 Docs
- 03_Phase_1_Lifecycle_and_Project_Enablement.md
- 07_Phase_1_Build_Book.md
- 11_Executable_Packets_Lifecycle.md
- 56_Phase_1_4_Installable_Project_Baseline_and_Managed_Asset_Synchronization.md
- [PKT-LFC-001](task-0045).md through [PKT-LFC-013](task-0055).md

#### Phase 4: Phase 2 Docs
- 04_Phase_2_Release_Audit_Ledger_and_Release_Please.md
- 08_Phase_2_Build_Book.md
- 12_Executable_Packets_Release_and_Ledger.md
- 23_Release_Please_Invocation.md
- 43_Phase_2_3_Project_Release_Bootstrap_and_Workflow_Activation.md
- [PKT-RLS-001](task-0056).md through [PKT-RLS-011](task-0066).md

#### Phase 5: Phase 3 Docs
- 05_Phase_3_Agent_Jobs_and_Simple_Workflows.md
- 09_Phase_3_Build_Book.md
- 13_Executable_Packets_Jobs_and_Workflows.md
- 35_Phase_3_2_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md
- 36_Prompt_Extension_Readiness_Assessment.md
- 37_Phase_3_3_Prompt_Tagged_Workflow_Shortcuts_and_Defaults.md
- 42_Phase_3_4_Job_Control_and_Running_Job_Cancellation.md
- [PKT-JOB-001](task-0067).md through [PKT-JOB-011](task-0077).md

#### Phase 6: Phase 4 Docs (Largest)
- 06_Phase_4_Providers_and_Optional_Server_Foundation.md
- 10_Phase_4_Build_Book.md
- 11_Phase_4_1_Provider_Model_Catalog_and_Selection.md
- 14_Executable_Packets_Providers_and_Optional_Server.md
- 38_Phase_4_3_Provider_Prompt_Tag_Surface_Integration.md
- 39_Phase_4_4_Provider_Tag_Execution_Implementation.md
- 40_Phase_4_6_Provider_Prompt_Trigger_Launch_Behavior.md
- 41_Phase_4_7_Provider_Auto_Install_Orchestration.md
- 45_Phase_4_9_Provider_Live_Stream_and_Progress_Capture.md
- 46_Phase_4_10_Provider_Live_Input_and_Interactive_Session_Control.md
- 47_Phase_4_11_Provider_Structured_Completion_and_Result_Normalization.md
- 48_Phase_4_12_Provider_Optimization_and_Shared_Workflow_Extensibility.md
- 55_Phase_4_13_Canonical_Prompt_Entry_and_Bridge_End_State.md
- 56_Phase_4_Remaining_Work_Execution_Guide.md
- [PKT-PRV-001](task-0078).md through [PKT-PRV-078](task-0156).md
- Provider plans and runbooks

#### Phase 7: Phase 5-6 Docs
- 07_Phase_5_Discord_Overlay.md
- 08_Phase_6_Migration_and_Cutover_Completion.md
- 12_Phase_6_Build_Book.md
- 15_Executable_Packets_Discord_and_Migration.md
- [PKT-DSC-001](task-0158).md through [PKT-DSC-004](task-0161).md
- [PKT-MIG-001](task-0162).md through [PKT-MIG-003](task-0164).md

#### Phase 8: Phase 7-11 Extension Docs
- 49_Phase_7_Node_Execution_Extension_Build_Book.md
- 50_Phase_8_Discovery_and_Registry_Extension_Build_Book.md
- 51_Phase_9_Distributed_Eventing_and_Control_Extension_Build_Book.md
- 52_Phase_10_Coordinator_Consumption_Seam_Build_Book.md
- 53_Phase_11_Pluggable_External_Tool_Connectivity_Build_Book.md
- 54_Build_Status_Registry_Extension_For_Phases_7_11.md
- [PKT-NOD-001](task-0165).md through [PKT-NOD-003](task-0167).md
- [PKT-DIS-001](task-0168).md through [PKT-DIS-003](task-0170).md
- [PKT-EVT-001](task-0171).md through [PKT-EVT-002](task-0172).md
- [PKT-CRD-001](task-0173).md
- [PKT-EXT-001](task-0174).md

#### Phase 9: Refactor and Testing Docs
- 57_Phase_0_3_Repository_Domain_Refactor_and_Package_Realignment.md
- Refactor phase-0.3 docs
- Testing and status reports

## Cross-Reference Patterns

### Common Reference Patterns

1. **Phase references:**
   - `06_Phase_0_Build_Book.md`
   - `07_Phase_1_Build_Book.md`
   - Pattern: `NN_Phase_X_Build_Book.md`

2. **Packet references:**
   - `packets/phase-0/[PKT-FND-001](task-0032).md`
   - Pattern: `packets/phase-X/PKT-XXX-NNN.md`

3. **Cross-phase references:**
   - `33_Phase_0_1_2_Readiness_and_Execution_Reference.md`
   - References multiple phases

4. **Draft docs:**
   - `26_DRAFT_Migration_Runbooks.md`
   - `28_DRAFT_Platform_Compatibility_and_Portability.md`
   - Pattern: `NN_DRAFT_Document_Name.md`

### Reference Types

1. **Internal links:** `[text](path/to/file.md)`
2. **Backtick references:** `` `01_Master_Implementation_Roadmap.md` ``
3. **Directory references:** `packets/phase-0/`
4. **Implicit references:** "See Phase 0 build book"

## Next Steps

1. **Migrate foundation docs** (Phase 1 above)
2. **Create planning objects** for each file
3. **Resolve references** during migration
4. **Link objects** using `tm_relink`
5. **Validate** with `tm_validate()`
6. **Delete old files** after validation

## Notes

- Phase 4 (providers) is the largest migration with 78+ packet files
- Provider plans and runbooks should be migrated as specs
- Packet files should be migrated as tasks
- Build books should be migrated as plans
- Foundation docs should be migrated first to establish structure
