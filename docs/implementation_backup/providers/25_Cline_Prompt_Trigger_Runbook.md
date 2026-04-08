# Cline prompt-trigger implementation runbook

## Purpose

Implement the Phase 4.6 Cline prompt-trigger path using `.clinerules`, hooks, workflows, and a
fallback bridge when hook interception is not available.

## Scope

- Cline chat surfaces
- Cline VS Code surfaces
- repo-local hooks/rules/workflows

## Exposure model

Cline is a native-intercept candidate. A prompt hook or equivalent entry point reads the first
non-empty line, resolves the canonical tag, and hands the normalized request to the matching
workflow or task mode.

## Current repo state

The repo now contains the Cline bridge surface required by this runbook:

- `.clinerules/prompt-tags.md`
- `.clinerules/review-policy.md`
- `.clinerules/skills/ag-*.md`
- `tools/cline_prompt_trigger_bridge.py`

## Required assets

- `.clinerules/prompt-tags.md`
- `.clinerules/review-policy.md`
- `.clinerules/skills/ag-plan.md`
- `.clinerules/skills/ag-implement.md`
- `.clinerules/skills/ag-review.md`
- `.clinerules/skills/ag-audit.md`
- `.clinerules/skills/ag-check-in-prep.md`
- Cline hook configuration
- Cline workflow files or task definitions
- repo-owned fallback bridge

These are provider-owned rendered surfaces. They are generated from the canonical
provider-function source under `.audiagentic/skills/`; Cline does not consume a single
generic provider-ready skill file format.

## Smoke tests

- `@ag-plan` reaches the shared launcher
- `@ag-implement` reaches the shared launcher
- `@ag-review` reaches the shared launcher

## Acceptance

- canonical tags are exposed in chat through hooks or fallback bridge
- Cline-specific instructions stay isolated
- fallback bridge works if hook interception is partial

## Live stream expectations (Phase 4.9)

Cline is a first-wave candidate for live console and runtime progress capture.

Implementation uses the PKT-PRV-048 generic sink harness.  Cline does not own any
persistence logic; it emits to stdout/stderr as normal and AUDiaGentic captures via sinks.

For the first pass:

- the bridge registers `ConsoleSink`, `RawLogSink`, and `NormalizedEventSink` for each Cline run
- a `ClineEventExtractor` sink (owned by the Cline adapter) translates Cline native NDJSON
  task-progress lines into canonical `provider-stream-event` records before they reach
  `NormalizedEventSink`
- `src/audiagentic/execution/providers/adapters/cline.py` is the owned implementation home for
  Cline-specific NDJSON parsing and extractor registration added by `PKT-PRV-050`
- console mirroring is controlled by `ConsoleSink` presence, not a boolean flag
- `events.ndjson` is written to the job runtime folder for every streaming-enabled run
- disabling streaming means not registering the sinks; the bridge path is otherwise unchanged
- the same sink interface is reusable later by Discord and other consumers without harness changes

Implementation note:
- `PKT-PRV-050` owns Cline-specific work in `src/audiagentic/execution/providers/adapters/cline.py`
- `PKT-PRV-048` continues to own only the shared sink harness

## Live input expectations (Phase 4.10)

Cline is also a first-wave candidate for live session input and interactive turns.

For the first pass:
- AUDiaGentic should own stdin/input capture and normalized session-input persistence
- AUDiaGentic should tee control/input turns to the console when interactive mode is enabled
- Cline should continue to emit responses normally and should not own file persistence
- the same input contract should remain usable later by Discord

## Related docs

- `docs/specifications/architecture/providers/07_Cline.md`
- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/implementation/packets/phase-4/PKT-PRV-037.md`
- `docs/implementation/providers/17_Cline_Tag_Execution_Implementation.md`
- `docs/specifications/architecture/35_Provider_Live_Input_and_Interactive_Session_Control.md`
- `docs/implementation/46_Phase_4_10_Provider_Live_Input_and_Interactive_Session_Control.md`
- `docs/implementation/packets/phase-4/PKT-PRV-051.md`
- `docs/implementation/packets/phase-4/PKT-PRV-048.md` — shared sink harness
- `docs/implementation/packets/phase-4/PKT-PRV-050.md` — Cline stream capture integration
