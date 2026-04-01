# Current Release

## Changes

### config
- [chg_20260330_0018] Added schemas for provider health checks and stage results.
- [chg_20260331_0003] Corrected the project-local bootstrap config to use the real AUDiaGentic identity.
- [chg_20260331_0004] Upgraded the release workflow to run the project bootstrap path and verify installed state.

### docs
- [chg_20260401_0001] Added the additive Phase 7-11 node/discovery/eventing/coordinator/tool-connectivity extension pack and updated the roadmap, indexes, registry, and target tree to keep it separate from baseline MVP work.
- [chg_20260401_0002] Cleaned up and aligned the additive Phase 7-11 extension docs, registry rows, and tracker wording so the new line reads consistently as additive future work.
- [chg_20260401_0003] Added bridge mechanics and defaults-first prompt syntax guidance to `AGENTS.md` so canonical tagged prompts map cleanly into the repo-owned launcher path.
- [chg_20260401_0004] Added a canonical prompt-entry and bridge end-state spec so every supported provider and prompt-entry surface is explicitly documented as converging on the same repo-owned bridge/launcher contract.
- [chg_20260401_0005] Consolidated the unimplemented Phase 4.9 through Phase 4.11 runtime interaction work into a single shared provider-session I/O tranche while keeping the packet numbering intact.
- [chg_20260401_0006] Folded the Phase 7+ node/discovery/federation/connectors extension layers into the canonical dependency rules, common contracts, target code tree, and live build registry.
- [chg_20260401_0007] Tightened the prompt-trigger rollout assessment and the live-stream/live-input specs with explicit Codex reference mechanics, guarded-provider graduation criteria, and the shared 4.9–4.11 runtime boundary notes.
- [chg_20260330_0019] Added progress report for Phase 3-4 completion.
- [chg_20260330_0021] Planned provider model catalog support and added Phase 4.1 tracking.
- [chg_20260330_0022] Documented incremental .1 phases and updated tracking before implementation.
- [chg_20260330_0023] Documented full packet breakdowns for incremental .1 phases.
- [chg_20260330_0024] Clarified the .1 packet scopes and dependencies before implementation.
- [chg_20260330_0025] Added the .2 workflow-launch extension docs and tracker updates.
- [chg_20260330_0030] Drafted Phase 4.6 provider prompt-trigger launch behavior and packet breakdowns.
- [chg_20260330_0031] Added a provider implementation snapshot to the current-state summary.
- [chg_20260330_0032] Drafted Phase 4.7 provider availability and auto-install orchestration and packet breakdowns.
- [chg_20260330_0033] Drafted Phase 1.3 provider auto-install policy persistence follow-on.
- [chg_20260330_0034] Expanded provider prompt-trigger docs with provider-specific chat exposure paths.
- [chg_20260330_0035] Added the Claude prompt-trigger implementation runbook.
- [chg_20260330_0036] Added the Gemini prompt-trigger implementation runbook.
- [chg_20260330_0037] Added the remaining provider prompt-trigger implementation runbooks.
- [chg_20260330_0038] Drafted Phase 3.4 job control and running-job cancellation.
- [chg_20260330_0039] Expanded the Phase 3.4 job-control packet into an implementation-ready packet.
- [chg_20260330_0041] Added the prompt-trigger rollout realism assessment.
- [chg_20260331_0001] Added project release bootstrap and workflow activation so the repo can install itself using its own release machinery.
- [chg_20260331_0002] Aligned the release bootstrap docs with the new project-level release-bootstrap entry point.
- [chg_20260331_0005] Formalized the provider prompt-calling mechanics map, starting with Codex as the reference bridge/skills path.
- [chg_20260331_0007] Drafted Phase 4.9 live stream and progress capture with first-wave Cline/Codex guidance.
- [chg_20260331_0008] Drafted Phase 4.10 live input and interactive session control with first-wave Cline/Codex guidance.
- [chg_20260331_0009] Implemented the shared Phase 4.10 live-input harness and session-input CLI, with test coverage.
- [chg_20260331_0012] Drafted Phase 4.12 provider optimization and shared workflow extensibility so shared scripts, skills, MCP tools, and wrappers can reduce token usage without locking in the future workflow model.
- [chg_20260331_0013] Tightened Phase 4.12 to be explicitly script-first and template-driven for repeatable operations, with agents limited to the minimum intent or parameters needed by the helper.

### feature
- [chg_20260330_0001] Added initial job persistence and state machine with tests.
- [chg_20260330_0002] Added workflow profile loading and override validation.
- [chg_20260330_0003] Added packet runner to execute workflow stages sequentially.
- [chg_20260330_0004] Added stage output persistence for job workflows.
- [chg_20260330_0005] Added job approval tracking with expiration handling.
- [chg_20260330_0006] Added job release bridge to update the change ledger.
- [chg_20260330_0007] Added provider registry and documented qwen provider support.
- [chg_20260330_0008] Added provider health checks and selection logic.
- [chg_20260330_0009] Added local-openai adapter stub for provider execution.
- [chg_20260330_0010] Added claude provider adapter stub.
- [chg_20260330_0011] Added codex provider adapter stub.
- [chg_20260330_0012] Added gemini provider adapter stub.
- [chg_20260330_0013] Added copilot provider adapter stub.
- [chg_20260330_0014] Added continue provider adapter stub.
- [chg_20260330_0015] Added cline provider adapter stub.
- [chg_20260330_0017] Added optional server seam for in-process job execution.
- [chg_20260330_0020] Added access-mode support for provider configuration and validation.
- [chg_20260330_0026] Implemented the Codex CLI provider wrapper and documented the remaining payload gap.
- [chg_20260330_0027] Implemented the Claude CLI provider wrapper and documented the remaining hook gap.
- [chg_20260330_0028] Implemented the Qwen CLI provider wrapper and documented the experimental hook gap.
- [chg_20260330_0029] Implemented the Cline CLI provider wrapper and documented the remaining hook gap.
- [chg_20260330_0040] Implemented Phase 3.4 job control and running-job cancellation.
- [chg_20260330_0042] Implemented the shared Phase 4.6 prompt-trigger bridge harness.
- [chg_20260330_0043] Added the Claude provider bridge surface and repo-local instruction rules.
- [chg_20260330_0044] Added the Cline provider bridge surface and repo-local instruction rules.
- [chg_20260330_0045] Added the Codex provider bridge surface and repo-local guidance.
- [chg_20260330_0046] Added the Gemini provider bridge surface and repo-local guidance.
- [chg_20260330_0047] Added the Copilot provider bridge surface and repo-local guidance.
- [chg_20260330_0048] Added the local-openai and Qwen bridge-only prompt-trigger surfaces.
- [chg_20260331_0010] Added configurable prompt-syntax profiles and alias normalization for tags, providers, and directive names.
- [chg_20260331_0005] Formalized the provider prompt-calling mechanics map, starting with Codex as the reference bridge/skills path.
- [chg_20260331_0006] Added Codex prompt-calling preflight validation and parked Continue as a future integration.
- [chg_20260331_0011] Wired configurable live-stream and live-input defaults through prompt launch, extended Codex/Cline/Gemini timeout defaults for longer reviews, and added shared streaming helpers in the Codex and Cline adapters.

### tests
- [chg_20260330_0016] Added provider/job seam tests.
