# PKT-PRV-052 — Codex live-input capture integration

**Phase:** Phase 4.10
**Status:** DEFERRED_DRAFT
**Primary owner:** Codex

## Purpose

Implement Codex-specific session-input handling on top of the shared live-input contract.

## Scope

- Codex stdin/input forwarding
- Codex session turn normalization
- live interactive clarification and follow-up input
- console mirroring where available

## Dependencies

- PKT-PRV-051 deferred draft or better
- PKT-PRV-005 verified
- PKT-PRV-032 ready for review or better

## Not in scope

- Codex prompt-trigger launch semantics
- provider execution model changes
- Discord publishing

## Files likely to change

- `src/audiagentic/execution/providers/adapters/codex.py`
- `tools/codex_prompt_trigger_bridge.py`
- `docs/implementation/providers/22_Codex_Prompt_Trigger_Runbook.md`
- Codex provider spec notes
- integration tests for session input

## Acceptance criteria

- Codex can accept a mid-run follow-up input turn through the bridge path.
- AUDiaGentic persists the input event stream.
- final structured output still lands in the job artifacts.
