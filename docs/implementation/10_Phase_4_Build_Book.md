# Phase 4 — Providers and optional server seam

This phase adds provider-driven execution without destabilizing the core. The provider seam is added on top of the job system, and the optional server seam is defined as a thin extraction boundary only. In-process execution remains the default and must stay first-class.

## Phase deliverables

See the packet files for exact build steps.

## Parallelization

Use the module ownership map to determine which packets may run at the same time after dependencies are merged.

## Exit gate

See `02_Phase_Gates_and_Exit_Criteria.md`.

## v12 corrective additions

Phase 4 now includes an explicit job/provider seam integration packet so provider attachment can be verified without rewriting Phase 3 job contracts.

Phase 4 uses **deterministic provider selection with no automatic failover in MVP**. Failover remains a DRAFT later enhancement.

Phase 4 includes a provider access-mode contract so CLI-authenticated providers can be configured explicitly without requiring stored API keys.

Phase 4.1 extends providers with model catalog and selection rules; see `11_Phase_4_1_Provider_Model_Catalog_and_Selection.md`.

Phase 4.2 adds provider status/validation CLI and catalog presence reporting; see `PKT-PRV-013`.
Phase 4.3 adds shared provider prompt-tag surface recognition and synchronization; see `38_Phase_4_3_Provider_Prompt_Tag_Surface_Integration.md`.
Phase 4.4 adds provider tag execution compliance and isolated provider implementation docs; see `39_Phase_4_4_Provider_Tag_Execution_Implementation.md`.
Phase 4.6 drafts provider prompt-trigger launch behavior and per-provider bridge/wrapper rollout; see `40_Phase_4_6_Provider_Prompt_Trigger_Launch_Behavior.md` and the realism assessment in `providers/28_Prompt_Trigger_Realistic_Rollout_Assessment.md`.
Phase 4.7 drafts provider availability and auto-install orchestration; see `41_Phase_4_7_Provider_Auto_Install_Orchestration.md`.
Phase 4.9 drafts provider live stream and progress capture; see `45_Phase_4_9_Provider_Live_Stream_and_Progress_Capture.md` and the rollout assessment in `providers/29_Provider_Live_Stream_Progress_Capture_Assessment.md`.
Phase 4.10 is now in progress for the shared live input and interactive session control harness; see `46_Phase_4_10_Provider_Live_Input_and_Interactive_Session_Control.md` and the rollout assessment in `providers/30_Provider_Live_Input_Interactive_Session_Assessment.md`.
