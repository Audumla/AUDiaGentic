# Current Release

## Changes

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

### tests
- [chg_20260330_0016] Added provider/job seam tests.
