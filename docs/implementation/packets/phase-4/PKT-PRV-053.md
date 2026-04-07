# PKT-PRV-053 — Cline live-input capture integration

**Phase:** Phase 4.10
**Status:** WAITING_ON_DEPENDENCIES
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

- `src/audiagentic/execution/providers/adapters/cline.py`
- `tools/cline_prompt_trigger_bridge.py`
- `docs/implementation/providers/25_Cline_Prompt_Trigger_Runbook.md`
- Cline provider spec notes
- integration tests for session input

## Acceptance criteria

- Cline can accept a mid-run follow-up input turn through the bridge path.
- AUDiaGentic persists the input event stream.
- final structured output still lands in the job artifacts.

## Entry criteria

Before starting, confirm all of the following are true:

- `PKT-PRV-051` is at least `READY_FOR_REVIEW`
- `PKT-PRV-037` is at least `READY_FOR_REVIEW`
- Cline launch/bridge flow already creates job runtime directories successfully
- the shared input contract and artifacts already exist in code and tests

## Config and runtime contract

- read `input-controls` from the normalized launch request / packet context
- project defaults come from `.audiagentic/project.yaml` under `prompt-launch.default-input-controls`
- do not create Cline-only input config keys in this packet
- use the shared runtime artifact layout:
  - `stdin.log`
  - `input.ndjson`
  - `input-events.ndjson`

## Implementation checklist

1. inspect the shared input harness and current Cline adapter flow
2. add Cline stdin/input forwarding in `src/audiagentic/execution/providers/adapters/cline.py`
3. ensure the bridge path can pass follow-up input turns into the active Cline run
4. persist input artifacts using the shared Phase 4.10 contract rather than Cline-specific files
5. add integration tests proving a mid-run follow-up turn is captured and persisted
6. update Cline runbook/spec notes if the actual interaction path changes

## Exit criteria

- Cline accepts at least one follow-up input turn through the bridge/runtime path
- shared input artifacts are written under the job runtime directory
- final structured output still persists after the interactive run
- no provider-specific input artifact layout is introduced

## Validation commands

```powershell
python -m pytest tests/integration/providers/test_cline.py -q
python -m pytest tests/integration/jobs -q
```
