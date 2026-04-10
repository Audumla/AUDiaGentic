# Archive Execution Report

## Branch

- `docs/archive-superseded-pre-acp-line`

## Starting commit

- `c88c80cb375234ff0e1d2e34180d6a0ee10c7ee0`

## Archived files

- `docs/specifications/architecture/11_Discord_Overlay_V1.md`
- `docs/specifications/architecture/providers/01_Local_OpenAI_Compatible.md`
- `docs/specifications/architecture/providers/06_Continue.md`
- `docs/implementation_backup/07_Phase_5_Discord_Overlay.md`
- `docs/implementation_backup/11_Phase_5_Build_Book.md`
- `docs/implementation_backup/15_Executable_Packets_Discord_and_Migration.md`
- `docs/implementation_backup/providers/01_Local_OpenAI_Compatible_Plan.md`
- `docs/implementation_backup/providers/06_Continue_Plan.md`
- `docs/implementation_backup/providers/16_Continue_Tag_Execution_Implementation.md`
- `docs/implementation_backup/providers/18_Local_OpenAI_Compatible_Tag_Execution_Implementation.md`
- `docs/implementation_backup/providers/24_Continue_Prompt_Trigger_Runbook.md`
- `docs/implementation_backup/providers/26_Local_OpenAI_Compatible_Prompt_Trigger_Runbook.md`
- `docs/implementation_backup/packets/phase-5/PKT-DSC-001.md`
- `docs/implementation_backup/packets/phase-5/PKT-DSC-002.md`
- `docs/implementation_backup/packets/phase-5/PKT-DSC-003.md`
- `docs/implementation_backup/packets/phase-5/PKT-DSC-004.md`
- `docs/implementation_backup/packets/phase-4/PKT-PRV-003.md`
- `docs/implementation_backup/packets/phase-4/PKT-PRV-008.md`
- `docs/implementation_backup/packets/phase-4/PKT-PRV-019.md`
- `docs/implementation_backup/packets/phase-4/PKT-PRV-021.md`
- `docs/implementation_backup/packets/phase-4/PKT-PRV-027.md`
- `docs/implementation_backup/packets/phase-4/PKT-PRV-029.md`
- `docs/implementation_backup/packets/phase-4/PKT-PRV-036.md`
- `docs/implementation_backup/packets/phase-4/PKT-PRV-038.md`
- `docs/implementation_backup/packets/phase-4/PKT-PRV-044.md`
- `docs/implementation_backup/packets/phase-4/PKT-PRV-046.md`

## Cancelled packets

- `PKT-DSC-001` through `PKT-DSC-004`
- `PKT-PRV-003`
- `PKT-PRV-008`
- `PKT-PRV-019`
- `PKT-PRV-021`
- `PKT-PRV-027`
- `PKT-PRV-029`
- `PKT-PRV-036`
- `PKT-PRV-038`
- `PKT-PRV-044`
- `PKT-PRV-046`

## Rewritten governing docs

- `docs/specifications/architecture/00_Architecture_Index.md`
- `docs/specifications/architecture/providers/00_Provider_Index.md`
- `docs/specifications/architecture/03_Common_Contracts.md`
- `docs/specifications/architecture/07_Agent_Server_and_Execution_Topology.md`
- `docs/implementation_backup/00_Implementation_Index.md`
- `docs/implementation_backup/01_Master_Implementation_Roadmap.md`
- `docs/implementation_backup/03_Target_Codebase_Tree.md`
- `docs/implementation_backup/31_Build_Status_and_Work_Registry.md`
- `docs/Implementation_tracker.md`

## Extracted reusable content

- smoke-test guidance patterns
- managed-surface generation ideas
- runtime artifact ownership expectations
- preflight validation patterns
- repo-local asset validation patterns

## Unresolved follow-ups

- Several non-governing architecture and implementation docs still mention Discord as a later consumer or still mention Continue/local-openai in secondary narrative sections.
- Qwen references that previously depended on combined local-openai/Qwen packet lines will need a clean replacement plan if that work remains desired.
- Code/config/schema references to retired provider ids and component ids remain a separate scope from this primarily documentation-and-registry pass.

## Remaining live docs still referencing archived work

- `docs/specifications/architecture/01_System_Overview.md`
- `docs/specifications/architecture/02_Core_Boundaries_and_Dependency_Rules.md`
- `docs/specifications/architecture/14_Approval_Core_and_Event_Model.md`
- `docs/specifications/architecture/20_Error_Envelope_and_Error_Codes.md`
- `docs/specifications/architecture/27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`
- `docs/specifications/architecture/28_Provider_Tag_Execution_Compliance_Model.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/specifications/architecture/34_Provider_Live_Stream_and_Progress_Capture.md`
- `docs/specifications/architecture/35_Provider_Live_Input_and_Interactive_Session_Control.md`
- `docs/specifications/architecture/36_Provider_Structured_Completion_and_Result_Normalization.md`
- multiple secondary files under `docs/implementation_backup/` that mention Discord as a later consumer or still mention Continue/local-openai in historical rollout narrative
