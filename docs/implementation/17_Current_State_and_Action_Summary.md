# Current State and Action Summary

## Current state

The documentation set is no longer at Phase 0 kickoff.
The current state is:

- Phases 1 through 4 core implementation are documented, while the provider-specific Phase 4.3 / 4.4 work is staged separately
- Phase 4.1 (`PKT-PRV-012`) is verified
- Phase 4.2 (`PKT-PRV-013`) is verified
- Phase 4.3 shared packet (`PKT-PRV-014`) is verified
- Phase 4.3 provider-specific rollout guidance now lives in Phase 4.4
- Phase 4.4 provider execution compliance docs are staged as the isolated provider-specific implementation layer
- `.1` through `.3` incremental packets are defined and complete
- `.4` prompt-tag surface integration is defined and ready to start
- `.5` provider execution compliance and isolated provider implementation docs have been added
- `.6` provider prompt-trigger launch behavior is now drafted as the next feature slice
- Phase 4.6 provider prompt-trigger docs now spell out the in-chat exposure path for each provider
- `docs/implementation/providers/28_Prompt_Trigger_Realistic_Rollout_Assessment.md` now captures the realistic provider-by-provider rollout order
- The shared prompt-trigger bridge harness for `PKT-PRV-031` is now implemented and test-covered
- Project release bootstrap and workflow activation is implemented so the repository can install and refresh itself using the same tracked release machinery it already owns
- Codex has its first provider-specific bridge path implemented through repo-local `AGENTS.md` and `.agents/skills` guidance plus a Codex wrapper bridge
- Claude has its first provider-specific bridge path implemented through repo-local guidance plus a Claude wrapper bridge
- Gemini has its first provider-specific bridge path implemented through repo-local `GEMINI.md` guidance plus a Gemini wrapper bridge
- Copilot has its first provider-specific bridge path implemented through repo-local `.github/copilot-instructions.md`, prompt files, agent files, and a Copilot wrapper bridge
- Cline now has its first provider-specific bridge path implemented through repo-local `.clinerules` guidance plus a Cline wrapper bridge
- local-openai now has its bridge-only prompt-trigger path implemented through the repo-owned wrapper bridge
- Qwen now has its bridge fallback prompt-trigger path implemented through the repo-owned wrapper bridge
- Claude and Cline are the strongest first-wave candidates for hook-backed rollout
- Codex and Continue should be treated as wrapper/bridge-first
- Gemini stays in the guarded group until its local hook behavior is proven; Qwen remains guarded for native hooks even though the bridge fallback is implemented
- `.7` provider availability and auto-install orchestration is now drafted as the next feature slice
- Phase 2.3 project release bootstrap and workflow activation is implemented and now tracked as a verified release-core extension
- Phase 1.3 provider auto-install policy persistence is drafted as a lifecycle follow-on
- Phase 3.4 job control and running-job cancellation is implemented and ready for review
- PKT-JOB-011 now has a concrete implementation packet with files, tests, and recovery steps
- The focused job-control test pass is green
- Phase 5 Discord overlay packets are now normalized and ready to implement

## Provider implementation snapshot

### Implemented and smoke-tested

- `local-openai` — adapter verified
- `claude` — CLI wrapper verified
- `codex` — CLI wrapper verified
- `cline` — CLI wrapper verified
- `copilot` — wrapper bridge verified
- `qwen` — CLI wrapper verified

### Implemented but still being tuned

- `gemini` — adapter exists, but the task-shaped wrapper still needs prompt-shape tuning

### Implemented, but not yet backed by the new prompt-trigger bridge layer

- `continue` — adapter exists, but the prompt-trigger bridge path is still a follow-on feature

### Prompt-trigger rollout realism

- first-wave: `claude`, `cline`
- wrapper/bridge-first: `codex`, `copilot`, `continue`
- guarded: `gemini`, `qwen`

### Implemented, but waiting on auto-install/bootstrap policy

- `local-openai`, `claude`, `codex`, `gemini`, `copilot`, `continue`, `cline`, and `qwen` can be configured now, and the shared auto-install/bootstrap policy is drafted, but provider-specific install packets are still pending implementation

This snapshot is intentionally coarse. The build registry remains the authoritative source for
packet-level status and the exact follow-on limitations.

## What is now required

1. continue using the build registry as the single live source of packet status
2. keep `.4` tracked as the shared provider-surface feature set, `.5` as the provider execution compliance layer, `.6` as the provider prompt-trigger launch bridge, and `.7` as the provider availability/bootstrap layer
3. use the prompt-trigger rollout assessment to decide the safest provider implementation order
4. avoid silently introducing alternate tracked config files or alternate prompt parsers
5. record prompt-launch, prompt-surface, provider-execution, and provider-install enhancements under their numbered slots
6. keep Phase 1.3 tracked as a lifecycle-only follow-on so provider install-policy fields round-trip cleanly

## Immediate action list

1. Use `PKT-PRV-014` as the shared prompt-tag surface reference already in place
2. Start `PKT-PRV-015` through `PKT-PRV-021` against the documented provider rollout guidance when ready
3. Use `PKT-PRV-022` as the shared provider-execution compliance reference
4. Keep `.4`, `.5`, `.6`, and `.7` tracked separately so the surface layer, execution layer, trigger layer, and install layer stay isolated
5. Continue using the build registry as the single live source of packet status
