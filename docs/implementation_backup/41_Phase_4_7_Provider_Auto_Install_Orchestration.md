# Phase 4.7 — Provider Auto-Install and Availability Orchestration

Phase 4.7 drafts the availability and auto-install layer that sits above provider execution
and prompt-trigger behavior. It is a project-local install/bootstrapping feature, not a new
provider grammar.

Status: draft only
Feature slot: .7

## Scope

This phase adds:
- a shared provider availability policy
- project-local install and bootstrap configuration
- provider-specific install packets for CLI, editor, and bridge-backed surfaces
- re-check logic after any installation attempt

This phase does not:
- change the prompt-launch contract
- change the prompt-trigger contract
- change provider execution semantics
- auto-install anything without explicit config permission

## Recommended implementation order

1. implement the shared availability and bootstrap contract
2. add Codex, Claude, and Gemini install packets first because they have the clearest local paths
3. add Copilot, Continue, and Cline install packets
4. finish with local-openai and qwen bridge/back-end availability packets

## Completion criteria for the draft

- provider availability can be probed without invoking the execution adapters
- install policy can opt into auto-install, prompt, skip, or manual behavior
- a missing provider can be bootstrapped only when the policy allows it
- post-install availability is re-probed before continuing
- provider-specific install steps can be tested independently

## Rollout guidance

- keep the shared availability check and bootstrap harness generic
- keep provider-specific install instructions isolated in provider packets
- use repo-local configuration to decide whether install is automatic or manual
- avoid merging install logic into provider execution adapters unless a provider truly requires it
