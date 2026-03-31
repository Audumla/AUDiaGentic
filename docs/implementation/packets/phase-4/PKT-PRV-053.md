# PKT-PRV-053 — Cline live-input capture integration

**Phase:** Phase 4.10
**Status:** DEFERRED_DRAFT
**Primary owner:** Cline

## Purpose

Implement Cline-specific session-input handling on top of the shared live-input contract.

## Scope

- Cline stdin/input forwarding
- Cline session turn normalization
- live interactive clarification and follow-up input
- console mirroring where available

## Dependencies

- PKT-PRV-051 deferred draft or better
- PKT-PRV-009 verified
- PKT-PRV-037 ready for review or better

## Not in scope

- Cline prompt-trigger launch semantics
- provider execution model changes
- Discord publishing

## Files likely to change

- `src/audiagentic/providers/adapters/cline.py`
- `tools/cline_prompt_trigger_bridge.py`
- `docs/implementation/providers/25_Cline_Prompt_Trigger_Runbook.md`
- Cline provider spec notes
- integration tests for session input

## Acceptance criteria

- Cline can accept a mid-run follow-up input turn through the bridge path.
- AUDiaGentic persists the input event stream.
- final structured output still lands in the job artifacts.
