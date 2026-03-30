# PKT-PRV-038 — local-openai/qwen prompt-trigger bridge integration

**Phase:** Phase 4.6
**Status:** READY_FOR_REVIEW
**Owner:** local-openai / qwen

## Objective
Wire backend-only or bridge-only surfaces to the shared trigger bridge so tagged prompts can launch jobs without provider-native interception.

## Current implementation

- `tools/local_openai_prompt_trigger_bridge.py` provides the local-openai wrapper path
- `tools/qwen_prompt_trigger_bridge.py` provides the Qwen wrapper path
- the shared bridge harness is already implemented and test-covered


## Prompt-trigger exposure details

local-openai and qwen are bridge-only surfaces for prompt-trigger launch. They do not own the
user-facing tag grammar themselves, so the repository bridge must expose the tags and map
them to a launch request before the backend sees any prompt text.

### User-facing flow
1. user types the tagged prompt into the project launcher or a bridge-enabled surface
2. the repo bridge reads the first non-empty line and resolves the canonical action
3. the bridge applies provider/model selection from the provider config and model catalog
4. the backend receives the normalized request, not the custom tag syntax

### Required files/settings
- repo-owned bridge script or launcher
- provider config model catalog and default-model settings
- bridge prompt-tag profile for the local-openai/qwen target surface
- optional editor command that invokes the same bridge

### Verification focus
- bridge smoke test for `@plan`
- bridge smoke test for `@review`
- backend availability check after the bridge call completes

### Failure mode
If the bridge is not available, the backend must be treated as tag-opaque and the provider
docs must not claim native prompt interception.

## Prerequisites
- PKT-PRV-031 is drafted
- PKT-PRV-003 is verified
- PKT-PRV-011 is verified

## Implementation steps
1. define the repo-owned bridge invocation for local-openai and qwen surfaces
2. keep model and provider selection in provider config, not in the shared grammar
3. document how the bridge is called from the local surface
4. add bridge-level prompt-trigger smoke tests

## Acceptance criteria
- backend-only prompt surfaces reach the shared launcher path through the bridge
- the bridge does not require provider-native prompt interception
- local-openai and qwen stay isolated as backend targets with a common bridge path

## Likely files or surfaces
- repo-owned bridge script or launcher
- provider config model catalog and default-model settings
- `docs/implementation/providers/26_Local_OpenAI_Compatible_Prompt_Trigger_Runbook.md`
- `docs/implementation/providers/27_Qwen_Prompt_Trigger_Runbook.md`
- bridge prompt-trigger smoke tests

## Rollback guidance
- revert the provider-specific trigger surface changes only
- leave the shared launch grammar untouched
