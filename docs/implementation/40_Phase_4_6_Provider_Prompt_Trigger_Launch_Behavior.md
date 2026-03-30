# Phase 4.6 — Provider Prompt-Trigger Launch Behavior

Phase 4.6 drafts the provider-owned behavior that turns tagged prompts into real launch
requests. It sits above the shared launch contract and below provider-specific instruction
surfaces.

Status: draft only
Feature slot: .6

## Scope

This phase adds:
- a shared prompt-trigger bridge contract
- provider-specific trigger surfaces and fallback rules
- wrapper/bridge invocation guidance for each provider
- smoke-test expectations for prompt-trigger launch

This phase does not:
- change the canonical prompt grammar
- change the Phase 3.2 launch request shape
- change the Phase 4.3 prompt-tag surface contract
- change the Phase 4.4 provider execution compliance model

## Recommended implementation order

1. implement the shared trigger bridge contract
2. add Claude and Cline first because they have the clearest hook-backed trigger surfaces
3. add Codex, Copilot, Continue, and local-openai as wrapper/bridge-first providers
4. add Gemini and Qwen with conservative fallback paths and feature gating
5. keep the rollout assessment current as provider surfaces are validated

## Completion criteria for the draft

- each provider packet has a stable instruction surface named in the spec
- each provider packet names the in-chat exposure asset or hook that actually sees the tag line
- the shared bridge contract is defined once and reused everywhere
- no provider packet redefines the canonical grammar
- per-provider smoke tests can validate that a tagged prompt reaches `prompt-launch`
- the draft can be implemented one provider at a time without overlapping write scopes

## Rollout guidance

- keep provider-local instructions minimal and declarative
- keep provider-specific chat exposure details in the provider packet, not in the shared grammar doc
- keep the shared bridge/wrapper responsible for normalization
- keep the jobs layer responsible for job creation and provenance persistence
- treat provider-specific trigger logic as a thin surface adapter, not a second workflow engine
- refer to `28_Prompt_Trigger_Realistic_Rollout_Assessment.md` before starting a provider packet
