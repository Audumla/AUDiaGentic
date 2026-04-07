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
Phase 4.6 now carries the active provider prompt-trigger launch behavior and per-provider bridge/wrapper rollout; see `40_Phase_4_6_Provider_Prompt_Trigger_Launch_Behavior.md` and the realism assessment in `providers/28_Prompt_Trigger_Realistic_Rollout_Assessment.md`.
Phase 4.7 drafts provider availability and auto-install orchestration; see `41_Phase_4_7_Provider_Auto_Install_Orchestration.md`.
Phase 4.9 now carries the active provider live stream and progress capture work; see `45_Phase_4_9_Provider_Live_Stream_and_Progress_Capture.md` and the rollout assessment in `providers/29_Provider_Live_Stream_Progress_Capture_Assessment.md`. Primary-provider extractor work is packetized in `PKT-PRV-049` and `PKT-PRV-050`; guarded-provider harness uplift is explicitly owned by `PKT-PRV-072` (Gemini) and `PKT-PRV-073` (Qwen).
Phase 4.9.1 is the post-implementation streaming hardening slice. It captures configuration-driven timeout support, bounded memory capture, sink-failure observability, normalized-event validation, serialized event writing, and stream-control validation after the baseline 4.9 harness is stable. Hardening defaults should prefer warnings, diagnostics, and explicit truncation markers over premature hard failures because some agents legitimately need long runtimes and large outputs.
Phase 4.10 is now in progress for the shared live input and interactive session control harness; see `46_Phase_4_10_Provider_Live_Input_and_Interactive_Session_Control.md` and the rollout assessment in `providers/30_Provider_Live_Input_Interactive_Session_Assessment.md`.
Phase 4.11 now has packetized primary-provider structured completion work; see `47_Phase_4_11_Provider_Structured_Completion_and_Result_Normalization.md`, the rollout matrix in `providers/31_Provider_Structured_Completion_And_Result_Normalization_Matrix.md`, and packets `PKT-PRV-056` through `PKT-PRV-058` plus `PKT-PRV-068`, `PKT-PRV-069`, and `PKT-PRV-071`.
Phase 4.4.1 is the shared provider-function generation sub-enhancement under the provider-surface foundation. It owns the canonical generic source, provider-specific surface generation, and managed-surface installation contract through `PKT-PRV-061`, `PKT-PRV-062`, `PKT-PRV-063`, and `PKT-PRV-070`. The shared tool is a facade/orchestrator; provider-specific rendering details stay with each provider. The first implementation of this infrastructure must include Codex, Claude, Cline, Gemini, and opencode so later provider work does not require revisiting the architecture. `PKT-PRV-061` and `PKT-PRV-070` are verified, and both `PKT-PRV-062` and `PKT-PRV-063` are now ready for review after the facade refactor and managed-surface validation work landed.

Phase 4.7 remains intentionally deferred. The current sequence skips from 4.6 to 4.9 because
stream/input/completion work can proceed independently of provider auto-install/bootstrap
orchestration, which is still a later policy and onboarding slice.
Phase 4.12 drafts provider optimization and shared workflow extensibility; see `48_Phase_4_12_Provider_Optimization_and_Shared_Workflow_Extensibility.md` and the reuse matrix in `providers/32_Provider_Optimization_and_Shared_Workflow_Extensibility_Matrix.md`. This phase is explicitly script-first and template-driven for repeatable work, and it now also owns the later shared execution-policy normalization packets `PKT-PRV-077` and `PKT-PRV-078` so provider adapters stop embedding policy flags and formats directly in code.

Phase 4.13 documents the canonical prompt-entry and bridge end state; see `55_Phase_4_13_Canonical_Prompt_Entry_and_Bridge_End_State.md`. It states the desired end functionality for all supported providers and prompt-entry surfaces: they converge on the same repo-owned bridge/launcher contract.

The later node/discovery/federation/connectors extension line starts at Phase 7 and is additive only; it does not replace or rewrite the Phase 4 provider foundation.


Phase 4 remaining implementation work should now be executed with `56_Phase_4_Remaining_Work_Execution_Guide.md` open beside the packet docs so file ownership, config locations, runtime artifacts, tests, and spec hooks stay explicit for each packet.
