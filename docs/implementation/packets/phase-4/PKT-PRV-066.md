# PKT-PRV-066 — opencode tag execution implementation

**Phase:** Phase 4.5
**Status:** READY_FOR_REVIEW
**Owner:** opencode

## Objective

Document and lock the end-to-end execution path for opencode tagged prompts so launch behavior,
provider execution, and fallback rules are explicit before broader provider work continues.

## What is implemented

- `docs/implementation/providers/19_Opencode_Tag_Execution_Implementation.md` now documents the
  opencode wrapper-first execution path using canonical `ag-*` tags
- the execution path explicitly routes tagged prompts through the shared prompt-trigger bridge
  and shared prompt-launch contract
- the provider adapter is the execution seam; opencode-specific semantics do not redefine the
  shared job or prompt grammar
- generated provider-function surfaces are the intended long-term source for provider-facing
  instruction content; opencode should not be documented as a “no skills” outlier

## Acceptance Criteria

- execution flow is documented end-to-end
- canonical tags are shown as `ag-*`
- wrapper-first behavior and bridge fallback are explicit
- opencode capabilities are described consistently with the generated provider-surface model
