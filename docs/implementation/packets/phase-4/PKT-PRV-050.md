# PKT-PRV-050 — Cline live-stream capture integration

**Phase:** Phase 4.9
**Status:** DEFERRED_DRAFT
**Primary owner group:** Cline

## Purpose

Wire the Cline prompt-trigger path so its rich task-progress output can be captured,
normalized, and mirrored by AUDiaGentic.

## Scope

- Cline CLI progress capture
- task-start / task-progress / completion record normalization
- console mirroring and runtime persistence
- review output capture for longer review tasks

## Dependencies

- PKT-PRV-048 deferred draft or better
- PKT-PRV-037 verified
- Cline CLI available

## Not in scope

- Cline model selection rewrite
- Cline hook ordering changes
- provider install/bootstrap work

## Files likely to change

- `tools/cline_prompt_trigger_bridge.py`
- `src/audiagentic/providers/adapters/cline.py`
- `src/audiagentic/jobs/prompt_launch.py`
- tests for streaming capture and review output

## Acceptance criteria

- Cline progress is visible during the run
- AUDiaGentic stores the live stream in runtime artifacts
- final review output still writes correctly
- the bridge remains usable when streaming is disabled
