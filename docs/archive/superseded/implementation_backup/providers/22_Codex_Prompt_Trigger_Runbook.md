# Codex prompt-trigger implementation runbook

## Purpose

Implement the Phase 4.6 Codex prompt-trigger path using the repo-owned wrapper, `AGENTS.md`,
and Codex skills.

## Scope

- Codex CLI
- Codex VS Code surface
- repo-owned wrapper / bridge

## Exposure model

Codex is wrapper-driven. A tagged prompt is recognized on the first non-empty line, normalized
by the repository bridge, and then handed to Codex as an explicit skill-directed request.

This is the reference prompt-calling path for the repo:
- first-line canonical tag
- repo-owned bridge
- `AGENTS.md` doctrine
- skill-directed execution
- shared `prompt-launch` handoff

## Current repo state

The repo now contains the Codex bridge surface required by this runbook:

- `AGENTS.md`
- `.agents/skills/ag-plan/SKILL.md`
- `.agents/skills/ag-implement/SKILL.md`
- `.agents/skills/ag-review/SKILL.md`
- `.agents/skills/ag-audit/SKILL.md`
- `.agents/skills/ag-check-in-prep/SKILL.md`
- no dedicated adhoc skill file; generic-tag launches are handled by the parser/bridge
- `tools/codex_prompt_trigger_bridge.py`

## Codex preflight contract

Before the bridge launches a job, the Codex prompt surface must verify that the project
contains:

- `AGENTS.md`
- the five canonical skill files

If any of those assets are missing, the bridge should fail fast with a validation error
instead of pretending the prompt-calling path is ready. That keeps the Codex path testable
and prevents the prompt-calling spec from drifting away from the actual repo state.

## Required assets

- `AGENTS.md`
- `.agents/skills/ag-plan/SKILL.md`
- `.agents/skills/ag-implement/SKILL.md`
- `.agents/skills/ag-review/SKILL.md`
- `.agents/skills/ag-audit/SKILL.md`
- `.agents/skills/ag-check-in-prep/SKILL.md`
- no dedicated adhoc skill file; generic-tag launches are handled by the parser/bridge
- repo-owned wrapper or bridge command

## Smoke tests

- `@ag-plan` reaches the shared launcher
- `@ag-implement` reaches the shared launcher
- `@ag-review` reaches the shared launcher
- `@ag-audit` and `@ag-check-in-prep` resolve through the same Codex bridge path
- missing required Codex assets return a validation error before launch

## Acceptance

- canonical tags are exposed in chat through the wrapper
- Codex-specific instructions stay isolated
- fallback bridge works if wrapper interception is partial
- the bridge validates `AGENTS.md` and the canonical skill files before launch

## Live stream expectations (Phase 4.9)

Codex is a first-wave candidate for live console and runtime progress capture.

Implementation uses the PKT-PRV-048 generic sink harness.  Codex does not own any
persistence logic; it emits to stdout/stderr as normal and AUDiaGentic captures via sinks.

For the first pass:

- the bridge registers `ConsoleSink`, `RawLogSink`, and `NormalizedEventSink` for each Codex run
- a `CodexEventExtractor` sink (owned by the Codex adapter) translates Codex wrapper milestone
  lines into canonical `provider-stream-event` records before they reach `NormalizedEventSink`
- `src/audiagentic/execution/providers/adapters/codex.py` is the owned implementation home for
  Codex-specific stream parsing and extractor registration added by `PKT-PRV-049`
- console mirroring is controlled by `ConsoleSink` presence, not a boolean flag
- `events.ndjson` is written to the job runtime folder for every streaming-enabled run
- disabling streaming means not registering the sinks; the bridge path is otherwise unchanged
- the same sink interface is reusable later by Discord and other consumers without harness changes

Implementation note:
- `PKT-PRV-049` owns Codex-specific work in `src/audiagentic/execution/providers/adapters/codex.py`
- `PKT-PRV-048` continues to own only the shared sink harness

## Live input expectations (Phase 4.10)

Codex is also a first-wave candidate for live session input and interactive turns.

For the first pass:
- AUDiaGentic should own stdin/input capture and normalized session-input persistence
- the Codex wrapper should tee live input or control turns to the console when interactive mode is enabled
- the provider should not be responsible for writing runtime input artifacts
- the same input contract should remain usable later by Discord

## Related docs

- `docs/specifications/architecture/providers/03_Codex.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-032.md`
- `docs/implementation/providers/12_Codex_Tag_Execution_Implementation.md`
- `docs/specifications/architecture/35_Provider_Live_Input_and_Interactive_Session_Control.md`
- `docs/implementation/46_Phase_4_10_Provider_Live_Input_and_Interactive_Session_Control.md`
- `docs/implementation/packets/phase-4/PKT-PRV-051.md`
- `docs/implementation/packets/phase-4/PKT-PRV-048.md` — shared sink harness
- `docs/implementation/packets/phase-4/PKT-PRV-049.md` — Codex stream capture integration
