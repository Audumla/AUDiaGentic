# PKT-PRV-067 — opencode prompt-trigger launch integration

**Phase:** Phase 4.6
**Status:** WAITING_ON_DEPENDENCIES
**Owner:** opencode

## Objective

Wire the opencode CLI wrapper to the shared trigger bridge so tagged prompts launch AUDiaGentic
jobs without introducing a provider-specific launch grammar.

## What is implemented

- `tools/opencode_prompt_trigger_bridge.py` exists and delegates to the shared
  `prompt-trigger-bridge`
- required repo-local assets are validated before launch
- integration coverage exists in
  `tests/integration/providers/test_opencode_prompt_trigger_bridge.py`
- tagged opencode prompts now reach the shared launcher path and create jobs with provider
  provenance preserved

## Current blocker

- the bridge implementation is reviewable in isolation, but end-to-end packet readiness still
  depends on `PKT-PRV-064` reaching `READY_FOR_REVIEW`

## Acceptance Criteria

- tagged opencode prompt reaches the shared launcher path
- provider-specific bridge preflight validation is implemented
- bridge path is documented and test-covered
