# Current State and Action Summary

## Current state

The documentation set is no longer at Phase 0 kickoff.
The current state is:

- Phases 1 through 4 core implementation are documented, while the provider-specific Phase 4.3 / 4.4 / 4.9 / 4.10 / 4.11 / 4.12 / 4.13 work is staged separately
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
- prompt-level `provider=` directives now explicitly override a surface default provider, so a Codex-launched prompt can intentionally hand off to Cline or another supported provider when the prompt asks for it
- Codex and opencode now have explicit preflight contracts that validate required repo-local assets before prompt-trigger launch
- `.8` project release bootstrap and workflow activation is complete so the repository can install itself using its own release processes
- `Phase 0.3` repository domain refactor and package realignment is now verified end to end: the checkpoint docs are frozen, the code/package move is complete, and the final validation gate has passed
- the refactor brief needed additional detail around package/import strategy, compatibility shims, deterministic tool placement, installable-baseline preservation, contracts/schemas location, test layout, and cross-domain dependency rules; those clarifications are now captured in the new Phase 0.3 spec and packets
- the Phase 0.3 checkpoint freeze did its job during the refactor window; with `PKT-FND-013` verified, later packets are now governed by their own dependencies again
- `PKT-FND-010` is now complete at the checkpoint-doc level: `repository-inventory.md`, `migration-map.md`, `ambiguity-report.md`, and `public-import-surface.md` exist and capture the live repository baseline for the refactor
- `PKT-FND-011` is now complete at the checkpoint-doc level: the new target tree, ownership map, repository-domain dependency rules, public import surface, shim scope, extension-root placement, and broad-code-motion definition are frozen before `PKT-FND-012`
- `Phase 1.4` installable project baseline sync is now fully verified: the inventory freeze, shared baseline-sync engine, and lifecycle/bootstrap convergence all landed on top of the verified refactored structure
- `.9` provider live stream and progress capture: spec 34 and implementation doc 45 are locked with a required generic `StreamSink` protocol; PKT-PRV-048 is now implemented and ready for review with `ConsoleSink`, `RawLogSink`, and `NormalizedEventSink` built-in sinks plus a `stdout_sinks`/`stderr_sinks` list API on `run_streaming_command`; PKT-PRV-049/050 remain the provider-extractor follow-ons, and Gemini is still an outlier because its adapter has not yet been uplifted onto the shared sink-based harness
- `.10` provider live input and interactive session control is in progress; the current harness records and persists session input, while full live-session attachment remains a later manager-level extension
- raw provider session keys are now explicitly treated as non-log-safe material; AUDiaGentic should preserve only redacted session handles in general runtime artifacts until a later secure-session reference/store seam is implemented
- prompt-launch now applies configurable default stream and input controls, so the shared bridge can tee live output and capture interactive turns without the provider owning persistence policy
- Codex, Cline, Claude, and opencode now share the sink-based streaming harness for baseline live output capture, while Gemini provider configs still carry longer timeout defaults so the streaming review path has room to complete long-running tasks
- Prompt tags, provider shorthands, and directive aliases are configurable through `.audiagentic/prompt-syntax.yaml`
- `.11` provider structured completion and result normalization is packetized and implementation-ready so each provider can use its best native surface while AUDiaGentic owns the canonical result shape
- `.11` provider structured completion and result normalization is now packetized into shared normalization plus Codex/Cline first-wave integrations so the build path is implementation-ready rather than docs-only
- `.4.1` canonical provider-function source and provider surface generation is now tracked as shared provider-surface infrastructure so generic provider-function content can be authored once and rendered into provider-specific outputs for every provider surface
- `.12` provider optimization and shared workflow extensibility is drafted so shared scripts, skills, MCP tools, and wrappers can reduce token usage without locking in the future workflow model; Phase 4.12 is explicitly script-first and template-driven for repeatable operations, and agents should only supply the minimum intent or parameters needed for the helper to do the work
- `.13` canonical prompt entry and bridge end state now explicitly states that every supported provider and prompt-entry surface converges on the same repo-owned bridge/launcher contract
- `.9` through `.11` are best implemented as one shared provider-session I/O and completion tranche for reuse, but they remain separate implementation packets with separate gates and review checkpoints
- a new future extension line now exists for Phase 7 through Phase 11: node execution, discovery/registry, federation/control, coordinator consumption, and connector connectivity; these are additive backend seams and remain outside the baseline MVP
- The shared prompt-trigger bridge harness for `PKT-PRV-031` is now implemented and test-covered
- Project release bootstrap and workflow activation is implemented so the repository can install and refresh itself using the same tracked release machinery it already owns
- Codex has its provider-specific bridge path implemented through repo-local `AGENTS.md` and `.agents/skills` guidance plus a Codex wrapper bridge
- Claude now has both its wrapper baseline and native hook path implemented, giving it a complete primary-provider path across wrapper and hook surfaces
- opencode now has its provider-specific bridge path implemented through `tools/opencode_prompt_trigger_bridge.py` plus the shared repo-local prompt/config assets
- opencode now has parity in `.audiagentic/providers.yaml`, so provider selection and config resolution can treat it as a configured first-class provider
- Gemini has a bridge wrapper and `GEMINI.md` doctrine; PKT-PRV-034 is IN_PROGRESS — `.gemini/commands/` per-tag templates and `BeforeAgent` hook config do not yet exist
- Copilot has a bridge wrapper and `.github/` scaffold; PKT-PRV-035 is IN_PROGRESS — all prompt/agent files are stubs and implement/audit/check-in-prep agents are missing
- Cline has `.clinerules/` doctrine and a bridge wrapper; PKT-PRV-037 is IN_PROGRESS — `.clinerules/skills/` per-tag files and hook config do not yet exist
- local-openai now has its bridge-only prompt-trigger path implemented through the repo-owned wrapper bridge
- Qwen now has its bridge fallback prompt-trigger path implemented through the repo-owned wrapper bridge
- Claude and Cline are the strongest hook-backed rollout candidates inside the primary provider set
- Codex and opencode are primary wrapper/bridge-first providers, and Continue is now a future integration outside the active rollout
- Gemini stays in the guarded group until its local hook behavior is proven; Qwen remains guarded for native hooks even though the bridge fallback is implemented
- `.7` provider availability and auto-install orchestration is now drafted as the next feature slice
- Phase 2.3 project release bootstrap and workflow activation is implemented and now tracked as a verified release-core extension
- Phase 1.3 provider auto-install policy persistence is drafted as a lifecycle follow-on
- Phase 1.4 installable project baseline and managed asset synchronization is now the install-focused correction layer that brings clean/existing project setup back into line with the repository's real tracked baseline; `PKT-LFC-011`, `PKT-LFC-012`, and `PKT-LFC-013` are all verified
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
- `opencode` — adapter and bridge exist, and provider-config parity is now in place; the remaining adapter work is focused on CLI correctness and broader edge-case coverage

### Implemented, but not yet backed by the new prompt-trigger bridge layer

- `continue` — adapter exists, but the prompt-trigger bridge path is still a follow-on feature

### Primary provider set

- primary providers: `codex`, `cline`, `claude`, `opencode`
- hook-capable within the primary set: `claude`, `cline`
- wrapper/bridge-first within the primary set: `codex`, `opencode`
- guarded outside the primary set: `gemini`, `qwen`

### Implemented, but waiting on auto-install/bootstrap policy

- `local-openai`, `claude`, `codex`, `gemini`, `copilot`, `continue`, `cline`, and `qwen` can be configured now, and the shared auto-install/bootstrap policy is drafted, but provider-specific install packets are still pending implementation
- `opencode` now joins that list with the new `.audiagentic/providers.yaml` entry in place

## Outstanding work and follow-ons

These are the intentional gaps still visible in the build registry:

- `Phase 4.7` provider availability and auto-install orchestration remains a draft and is not yet implemented.
- `Phase 1.3` provider auto-install policy persistence remains a lifecycle follow-on so the install policy fields can round-trip safely.
- `PKT-PRV-017` / Gemini prompt-trigger behavior is implemented through the bridge path, but the native hook surface still needs runtime hardening before it should be treated as the strongest path.
- `Continue` is now deferred as a future integration and is intentionally outside the active prompt-calling rollout.
- `PKT-JOB-011` currently provides cooperative cancellation; a true hard OS-level kill remains a follow-on if we decide we need it.
- `Phase 4.9` provider live stream and progress capture: PKT-PRV-048 is READY_FOR_REVIEW with the shared sink harness, event schemas, Windows-safe console mirroring, and adapter uplift in place across Codex, Cline, Claude, and opencode; PKT-PRV-049/050 remain READY_TO_START for provider-specific extractor work, and guarded-provider harness uplift is now explicitly owned by `PKT-PRV-072` (Gemini) and `PKT-PRV-073` (Qwen).
- Gemini and Qwen still bypass the shared stream/input harness through raw `subprocess.run(...)` adapter paths, so they should not be treated as fully Phase 4.9 / 4.10 compliant until those uplift packets land.
- `Phase 4.10` provider live input and interactive session control is in progress; the current harness records and persists session input, while full live-session attachment remains a later manager-level extension.
- `PKT-PRV-052` through `PKT-PRV-054` are now waiting on the shared input harness and provider launch packets rather than being treated as disconnected drafts.
- `PKT-PRV-054` captures the follow-on requirement that raw provider session keys must not be written into durable runtime logs; a secure-session reference/store seam is deferred for a later slice.
- prompt-launch now merges project-level default stream and input controls before provider execution, so live output capture and interactive session recording stay AUDiaGentic-owned.
- Provider-specific auto-install packets remain intentionally deferred until the shared `PKT-PRV-039` contract and bootstrap harness are implemented.
- Cline review launches are executing through the bridge, but the provider still needs prompt-shape hardening to reliably return structured JSON instead of falling back to a synthetic review bundle.
- `Phase 4.11` provider structured completion and result normalization is the next feature slice so Codex, Cline, Claude, and opencode can return canonical review/output payloads without duplicating the shared bridge harness, with Gemini already added to the planned packet family so the completion architecture does not need to be reopened later.
- `PKT-PRV-056` through `PKT-PRV-058` plus `PKT-PRV-068`, `PKT-PRV-069`, and `PKT-PRV-071` now define the primary packet path for structured completion and result normalization.
- the active Phase 4 critical path is now `Phase 4.4.1` canonical provider-function generation followed by `PKT-PRV-056` shared structured completion and then the primary-provider completion packets; older `READY_TO_START` rows in Phase 4.3 / 4.4 are mostly legacy documentation closeout rather than the main implementation path
- `Phase 4.12` provider optimization and shared workflow extensibility is the following slice so scripts, skills, MCP tools, and wrappers can reduce token usage without locking in the future workflow model, and it is script-first/template-driven for repeatable operations with agents limited to the minimum intent or parameters needed for the helper to do the work.
- `Phase 4.4.1` canonical provider-function source and provider surface generation is the foundational shared generation slice; `PKT-PRV-061`, `PKT-PRV-062`, `PKT-PRV-063`, and `PKT-PRV-070` own the generic source, shared regeneration facade, provider-owned renderer pattern, and managed-surface policy for every provider.
- `PKT-PRV-061` is now verified, so the canonical-source migration work can proceed without further tag-name refactor blockers.
- `.audiagentic/skills/` now exists with one canonical generic source file per core `ag-*` function, `.audiagentic/prompt-syntax.yaml` now carries the `skill-surfaces` dispatch config, legacy duplicate unprefixed skill folders have been removed, and the shared regeneration facade now renders Codex/Claude/Cline/Gemini/opencode surfaces with managed headers; `PKT-PRV-070` is verified, and both `PKT-PRV-062` and `PKT-PRV-063` are now ready for review.
- `Spec 50` (`docs/specifications/architecture/50_Template_Installation_and_Managed_Surface_Contract.md`) now exists as the managed-surface contract draft; `PKT-PRV-063` remains open because managed headers and `check_baseline_assets.py --check-managed-headers` still need implementation.
- Gemini is now intentionally part of the foundational provider-function generation set so `.gemini/commands/` and later Gemini completion/instruction surfaces are designed in from the start rather than bolted on as a special late exception.
- `Phase 4.13` canonical prompt entry and bridge end state explicitly states that every supported provider and prompt-entry surface converges on the same repo-owned bridge/launcher contract.
- `Phase 7` through `Phase 11` are new additive backend extension phases and are intentionally future work; they must not change baseline lifecycle, release, job, or provider contracts.
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
2. keep `.4` tracked as the shared provider-surface feature set, `.5` as the provider execution compliance layer, `.6` as the provider prompt-trigger launch bridge, `.7` as the provider availability/bootstrap layer, `.8` as the project release bootstrap layer, `.9` as the provider live-stream capture layer, `.10` as the live-input capture layer, `.11` as the structured completion/result layer, `.12` as the optimization layer, and `.13` as the canonical prompt-entry end-state layer; do not merge `.9` through `.11` into one packet even though they share implementation seams
3. use the prompt-trigger rollout assessment to decide the safest provider implementation order
4. avoid silently introducing alternate tracked config files or alternate prompt parsers
5. record prompt-launch, prompt-surface, provider-execution, provider-install, provider-live-stream, provider-live-input, provider-completion, and provider-optimization enhancements under their numbered slots
6. keep Phase 1.3 tracked as a lifecycle-only follow-on so provider install-policy fields round-trip cleanly

## Immediate action list

1. Continue using the build registry as the single live source of packet status
2. Keep the installable-baseline inventory and runtime exclusion rules aligned as future baseline assets evolve
3. Keep all new work on the canonical repository-domain paths only; the legacy shim roots have been retired
4. Resume the next legal non-checkpoint packet from the registry
