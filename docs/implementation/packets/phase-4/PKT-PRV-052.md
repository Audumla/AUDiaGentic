# PKT-PRV-052 — Codex live-input capture integration

**Phase:** Phase 4.10
**Status:** WAITING_ON_DEPENDENCIES
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

## Entry criteria

Before starting, confirm all of the following are true:

- `PKT-PRV-051` is at least `READY_FOR_REVIEW`
- `PKT-PRV-032` is at least `READY_FOR_REVIEW`
- Codex launch/bridge flow already creates job runtime directories successfully
- the shared input contract and artifacts already exist in code and tests

## Config and runtime contract

- read `input-controls` from the normalized launch request / packet context
- project defaults come from `.audiagentic/project.yaml` under `prompt-launch.default-input-controls`
- do not create Codex-only input config keys in this packet
- use the shared runtime artifact layout:
  - `stdin.log`
  - `input.ndjson`
  - `input-events.ndjson`

## Implementation checklist

1. inspect the shared input harness and current Codex adapter flow
2. add Codex stdin/input forwarding in `src/audiagentic/execution/providers/adapters/codex.py`
3. ensure the bridge path can pass follow-up input turns into the active Codex run
4. persist input artifacts using the shared Phase 4.10 contract rather than Codex-specific files
5. add integration tests proving a mid-run follow-up turn is captured and persisted
6. update Codex runbook/spec notes if the actual interaction path changes

## Exit criteria

- Codex accepts at least one follow-up input turn through the bridge/runtime path
- shared input artifacts are written under the job runtime directory
- final structured output still persists after the interactive run
- no provider-specific input artifact layout is introduced

## Validation commands

```powershell
python -m pytest tests/integration/providers/test_codex.py -q
python -m pytest tests/integration/jobs -q
```
