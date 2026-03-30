# PKT-PRV-034 — Gemini prompt-trigger launch integration

**Phase:** Phase 4.6
**Status:** READY_FOR_REVIEW
**Owner:** Gemini

## Objective
Wire Gemini instruction surfaces or command templates to the shared trigger bridge so tagged prompts can launch jobs.

## Current implementation

- `GEMINI.md` now records the canonical tag doctrine and bridge usage
- `tools/gemini_prompt_trigger_bridge.py` provides the Gemini-specific wrapper path to the shared bridge
- the shared bridge harness is already implemented and test-covered


## Prompt-trigger exposure details

Gemini exposes tags through workspace instructions and command templates, with any available
submit hook or wrapper normalizing the first line before the chat loop starts.

### User-facing flow
1. user types the tagged prompt into Gemini CLI or the Gemini Code Assist surface
2. the active hook or bridge reads the first non-empty line and resolves the canonical action
3. `GEMINI.md` and the prompt-tag settings profile keep the tag mapping stable
4. the normalized envelope is submitted to Gemini through the selected surface

### Required files/settings
- `GEMINI.md`
- command templates for plan / implement / review / audit / check-in-prep
- optional prompt-submit hook or wrapper script
- Gemini prompt-tag settings profile

### Verification focus
- CLI smoke test for `@plan`
- CLI smoke test for `@review`
- editor-surface smoke test if the Gemini companion exposes one in the active build

### Failure mode
If the active Gemini build does not expose a stable submit hook, the repository bridge must
remain authoritative and the native path should be treated as partial.

## Prerequisites
- PKT-PRV-031 is drafted
- PKT-PRV-006 is verified

## Implementation steps
1. define or update GEMINI.md guidance and command templates
2. bridge Gemini prompt submission to the shared launch wrapper
3. keep Gemini-specific launch notes isolated from the shared grammar
4. add Gemini prompt-trigger smoke tests

## Acceptance criteria
- tagged Gemini prompts reach the shared launcher path
- Gemini-specific instruction files do not redefine the canonical grammar
- the chosen launch path remains stable under smoke tests

## Likely files or surfaces
- GEMINI.md
- Gemini command templates
- docs/implementation/providers/21_Gemini_Prompt_Trigger_Runbook.md
- Gemini prompt-trigger smoke tests

## Rollback guidance
- revert the provider-specific trigger surface changes only
- leave the shared launch grammar untouched
