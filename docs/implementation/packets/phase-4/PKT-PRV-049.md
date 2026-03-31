# PKT-PRV-049 — Codex live-stream capture integration

**Phase:** Phase 4.9
**Status:** DEFERRED_DRAFT
**Primary owner group:** Codex

## Purpose

Wire the Codex prompt-trigger path so live output can be captured and mirrored through the
shared Phase 4.9 stream harness.

## Scope

- Codex bridge stream capture
- Codex stdout/stderr passthrough
- normalized progress event emission
- final structured artifact preservation

## Dependencies

- PKT-PRV-048 deferred draft or better
- PKT-PRV-032 verified
- Codex CLI path available

## Not in scope

- Codex execution semantics rewrite
- provider model catalog changes
- prompt syntax changes

## Files likely to change

- `tools/codex_prompt_trigger_bridge.py`
- `src/audiagentic/providers/adapters/codex.py`
- `src/audiagentic/jobs/prompt_launch.py`
- tests for streaming capture

## Acceptance criteria

- Codex can run with live output visible in the console
- AUDiaGentic writes normalized progress records for the run
- final structured output remains available after the run
- the bridge still works when streaming is disabled
