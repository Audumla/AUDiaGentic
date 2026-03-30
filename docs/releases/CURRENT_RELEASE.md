# Current Release

## Changes

### config
- [chg_20260330_0018] Added schemas for provider health checks and stage results.

### docs
- [chg_20260330_0019] Added progress report for Phase 3-4 completion.
- [chg_20260330_0021] Planned provider model catalog support and added Phase 4.1 tracking.
- [chg_20260330_0022] Documented incremental .1 phases and updated tracking before implementation.
- [chg_20260330_0023] Documented full packet breakdowns for incremental .1 phases.
- [chg_20260330_0024] Clarified the .1 packet scopes and dependencies before implementation.
- [chg_20260330_0025] Added the .2 workflow-launch extension docs and tracker updates.
- [chg_20260330_0041] Added the prompt-trigger rollout realism assessment and aligned Phase 4.6 provider docs to it.
- [chg_20260330_0043] Added the Claude provider bridge surface, repo-local Claude guidance, and packet updates for the first provider-specific Phase 4.6 path.
- [chg_20260330_0044] Added the Cline provider bridge surface, repo-local Cline guidance, and packet updates for the second provider-specific Phase 4.6 path.
- [chg_20260330_0045] Added the Codex provider bridge surface, repo-local Codex guidance, and packet updates for the third provider-specific Phase 4.6 path.
- [chg_20260330_0046] Added the Gemini provider bridge surface, repo-local Gemini guidance, and packet updates for the fourth provider-specific Phase 4.6 path.
- [chg_20260330_0047] Added the Copilot provider bridge surface, repo-local Copilot guidance, and packet/tracking updates for the fifth provider-specific Phase 4.6 path.
- [chg_20260330_0048] Added the local-openai and Qwen bridge-only prompt-trigger surfaces, repo-local bridge wrappers, and packet/tracking updates for the backend-only Phase 4.6 path.

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
- [chg_20260330_0026] Added a real Codex CLI provider wrapper with smoke tests and documented the remaining task-payload limitation.
- [chg_20260330_0027] Added a real Claude CLI provider wrapper with smoke tests and documented the remaining hook/skills limitation.
- [chg_20260330_0028] Added a real Qwen CLI provider wrapper with smoke tests and documented the remaining experimental hook limitation.
- [chg_20260330_0029] Added a real Cline CLI provider wrapper with smoke tests and documented the remaining native-hook hardening path.
- [chg_20260330_0030] Drafted Phase 4.6 provider prompt-trigger launch behavior and provider-by-provider packet breakdown.
- [chg_20260330_0031] Added a compact provider implementation snapshot to the current-state summary.
- [chg_20260330_0032] Drafted Phase 4.7 provider availability and auto-install orchestration and provider-by-provider packet breakdown.
- [chg_20260330_0033] Drafted Phase 1.3 provider auto-install policy persistence and lifecycle roundtrip follow-on.
- [chg_20260330_0034] Expanded provider prompt-trigger docs with provider-specific in-chat tag exposure paths and packet details.
- [chg_20260330_0035] Added the Claude prompt-trigger implementation runbook for the first native-hook rollout path.
- [chg_20260330_0036] Added the Gemini prompt-trigger implementation runbook for hook-or-bridge rollout.
- [chg_20260330_0037] Added the remaining provider prompt-trigger implementation runbooks for Codex, Copilot, Continue, Cline, local-openai, and Qwen.
- [chg_20260330_0038] Drafted Phase 3.4 job control and running-job cancellation as a dedicated job-layer control path.
- [chg_20260330_0039] Expanded the Phase 3.4 job-control packet into an implementation-ready packet with files, tests, and recovery steps.
- [chg_20260330_0040] Implemented Phase 3.4 job control and running-job cancellation with CLI, control record, runner checks, and tests.
- [chg_20260330_0042] Implemented the shared Phase 4.6 prompt-trigger bridge harness with CLI support and test coverage.

### tests
- [chg_20260330_0016] Added provider/job seam tests.
