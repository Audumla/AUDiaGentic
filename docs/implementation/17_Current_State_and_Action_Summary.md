# Current State and Action Summary

## Current state

The documentation set is no longer at Phase 0 kickoff.
The current state is:

- Phases 1 through 4 core implementation are documented, while the provider-specific Phase 4.3 / 4.4 / 4.9 / 4.10 / 4.11 / 4.12 work is staged separately
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
- `docs/implementation/providers/28_Prompt_Trigger_Realistic_Rollout_Assessment.md` now also captures the provider prompt-calling mechanics map, starting with Codex and then mirroring the remaining providers
- Codex now has an explicit preflight contract that validates `AGENTS.md` and the canonical skill files before prompt-trigger launch
- `.8` project release bootstrap and workflow activation is complete so the repository can install itself using its own release processes
- `.9` provider live stream and progress capture is drafted, with Cline and Codex as the first-wave validation providers and Discord later consuming the same stream contract
- `.10` provider live input and interactive session control is in progress; the shared harness is implemented and test-covered, with Cline and Codex next and Discord later consuming the same input contract
- prompt-launch now applies configurable default stream and input controls, so the shared bridge can tee live output and capture interactive turns without the provider owning persistence policy
- Codex, Cline, and Gemini provider configs now carry longer timeout defaults so the streaming review path has room to complete long-running tasks
- Prompt tags, provider shorthands, and directive aliases are configurable through `.audiagentic/prompt-syntax.yaml`
- `.11` provider structured completion and result normalization is drafted so each provider can use its best native surface while AUDiaGentic owns the canonical result shape
- `.12` provider optimization and shared workflow extensibility is drafted so shared scripts, skills, MCP tools, and wrappers can reduce token usage without locking in the future workflow model
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
- Codex should be treated as wrapper/bridge-first, and Continue is now a future integration outside the active rollout
- Gemini stays in the guarded group until its local hook behavior is proven; Qwen remains guarded for native hooks even though the bridge fallback is implemented
- `.7` provider availability and auto-install orchestration is now drafted as the next feature slice
- Phase 2.3 project release bootstrap and workflow activation is implemented and now tracked as a verified release-core extension
- Phase 1.3 provider auto-install policy persistence is drafted as a lifecycle follow-on
- Phase 3.4 job control and running-job cancellation is implemented and ready for review
- PKT-JOB-011 now has a concrete implementation packet with files, tests, and recovery steps
- The focused job-control test pass is green
- Phase 5 Discord overlay packets are now normalized and ready to implement
- The current stable release point is tagged `stable-release-20260331` at merge commit `4e01b4ef962cf80c8f6fe912f1b6a7cba22bcb32`

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
- wrapper/bridge-first: `codex`, `copilot`
- guarded: `gemini`, `qwen`

### Implemented, but waiting on auto-install/bootstrap policy

- `local-openai`, `claude`, `codex`, `gemini`, `copilot`, `continue`, `cline`, and `qwen` can be configured now, and the shared auto-install/bootstrap policy is drafted, but provider-specific install packets are still pending implementation

## Outstanding work and follow-ons

These are the intentional gaps still visible in the build registry:

- `Phase 4.7` provider availability and auto-install orchestration remains a draft and is not yet implemented.
- `Phase 1.3` provider auto-install policy persistence remains a lifecycle follow-on so the install policy fields can round-trip safely.
- `PKT-PRV-017` / Gemini prompt-trigger behavior is implemented through the bridge path, but the native hook surface still needs runtime hardening before it should be treated as the strongest path.
- `Continue` is now deferred as a future integration and is intentionally outside the active prompt-calling rollout.
- `PKT-JOB-011` currently provides cooperative cancellation; a true hard OS-level kill remains a follow-on if we decide we need it.
- `Phase 4.9` provider live stream and progress capture remains a draft and is not yet implemented.
- `Phase 4.10` provider live input and interactive session control is in progress; the shared harness is implemented and the provider-specific follow-ons are next.
- prompt-launch now merges project-level default stream and input controls before provider execution, so live output capture and interactive session recording stay AUDiaGentic-owned.
- Provider-specific auto-install packets remain intentionally deferred until the shared `PKT-PRV-039` contract and bootstrap harness are implemented.
- Cline review launches are executing through the bridge, but the provider still needs prompt-shape hardening to reliably return structured JSON instead of falling back to a synthetic review bundle.
- `Phase 4.11` provider structured completion and result normalization is the next feature slice so Cline, Codex, and the remaining providers can return canonical review/output payloads without duplicating the shared bridge harness.
- `Phase 4.12` provider optimization and shared workflow extensibility is the following slice so scripts, skills, MCP tools, and wrappers can reduce token usage without locking in the future workflow model.
- The remaining prompt-calling work is now mostly documentation and provider-instruction hardening: Codex is the reference mechanics path, and the other provider surfaces reuse the same shared bridge contract with provider-specific surfaces.

## Issue / work tracking process

Use the build registry as the live issue board:

- `READY_TO_START` means the packet can begin now.
- `IN_PROGRESS` means the work is actively underway.
- `BLOCKED` means the packet is waiting on a documented dependency or missing tool/state.
- `READY_FOR_REVIEW` means the work is complete and should be reviewed or merged.
- `DEFERRED_DRAFT` means the packet is intentionally parked for a later phase or gated by a missing prerequisite.

If a new issue is discovered during implementation, capture it in the packet or current-state summary before moving on. That keeps the project usable as its own progress tracker and makes it easier to turn into a first-class issue/work management layer later.

This snapshot is intentionally coarse. The build registry remains the authoritative source for
packet-level status and the exact follow-on limitations.

## What is now required

1. continue using the build registry as the single live source of packet status
2. keep `.4` tracked as the shared provider-surface feature set, `.5` as the provider execution compliance layer, `.6` as the provider prompt-trigger launch bridge, `.7` as the provider availability/bootstrap layer, `.8` as the project release bootstrap layer, `.9` as the provider live-stream capture layer, `.10` as the live-input capture layer, and `.11` as the structured completion/result layer
3. use the prompt-trigger rollout assessment to decide the safest provider implementation order
4. avoid silently introducing alternate tracked config files or alternate prompt parsers
5. record prompt-launch, prompt-surface, provider-execution, provider-install, provider-live-stream, provider-live-input, provider-completion, and provider-optimization enhancements under their numbered slots
6. keep Phase 1.3 tracked as a lifecycle-only follow-on so provider install-policy fields round-trip cleanly

## Immediate action list

1. Use `PKT-PRV-014` as the shared prompt-tag surface reference already in place
2. Start `PKT-PRV-015` through `PKT-PRV-021` against the documented provider rollout guidance when ready
3. Use `PKT-PRV-022` as the shared provider-execution compliance reference
4. Keep `.4`, `.5`, `.6`, `.7`, `.8`, `.9`, `.10`, `.11`, and `.12` tracked separately so the surface layer, execution layer, trigger layer, install layer, release-bootstrap layer, live-stream layer, live-input layer, completion layer, and optimization layer stay isolated
5. Continue using the build registry as the single live source of packet status
