# Provider tag execution compliance model

Status: additive architecture extension  
Related documents:
- `26_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md`
- `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`
- `docs/implementation/providers/11_Provider_Tag_Execution_Conformance_Matrix.md`
- `docs/implementation/39_Phase_4_4_Provider_Tag_Execution_Implementation.md`

## Purpose

This document freezes the architecture rule for provider-side execution of canonical
prompt tags.

The original requirement was that prompts entered through supported CLI and VS Code
surfaces should be able to launch workflow-aligned actions such as planning,
implementation, review, and audit. This architecture note makes that requirement
implementable without falsely assuming every provider exposes the same interception
mechanisms.

## Rule of truth

Canonical prompt tags are part of the AUDiaGentic system contract, not part of any single
provider product contract.

Providers comply in one of three ways:
1. native intercept
2. mapped execution via thin adapter
3. backend-only participation

## Canonical tags

- `@plan`
- `@implement`
- `@review`
- `@audit`
- `@check-in-prep`
- optional `@adhoc`

These tags are only valid when they appear as the first actionable token in the prompt
surface selected for provider execution.

## Canonical request envelope

Every provider must normalize into the same launch envelope before job execution.

Minimum required fields:
- `version`
- `tag`
- `raw_prompt`
- `normalized_payload`
- `source.provider`
- `source.surface`
- `source.session_id` when available
- `target.kind`
- `target.ref`
- `requested_stage`
- `review.mode`
- `provider.execution_mode`
- `provider.adapter_mode`

## Compliance levels

### Level A — Native intercept

The provider surface can intercept user prompt submission before planning.  
Examples in current provider set:
- Claude Code
- Gemini CLI / Gemini Code Assist
- Cline
- Qwen Code (experimental hooks)

### Level B — Mapped execution

The provider surface supports reusable commands, prompts, skills, agents, or workflows,
but not deterministic first-line tag interception.  
Examples in current provider set:
- Codex
- GitHub Copilot

### Level C — Backend only

The provider is only a model transport / endpoint.  
Examples:
- backend-only endpoints behind another active client or bridge surface

## Non-negotiable constraints

1. provider implementations may change syntax handling, but not semantics
2. provider implementations must preserve provenance
3. provider implementations must honor stage-specific tool restrictions
4. provider implementations must not directly write tracked docs outside the approved flow
5. provider parity is measured by canonical smoke tests, not by file-level similarity

## Thin adapter doctrine

A thin adapter is allowed only when the provider lacks native first-line interception.

Allowed responsibilities:
- detect canonical tag
- parse target payload
- validate supported tag
- construct canonical envelope
- invoke provider-native command/skill/agent/workflow
- attach provenance and policy mode

Disallowed responsibilities:
- invent provider-only tag meanings
- bypass review restrictions
- bypass approval policy
- skip envelope creation
- create alternative artifact semantics

## Native-first doctrine

If a provider supports prompt-submit or before-agent hooks, use native interception first.
Only use wrappers when the native interception route is unavailable, unstable, or not
portable across the provider's CLI and editor surfaces.

## `@adhoc`

`@adhoc` is part of the design baseline but may remain feature-gated during the first
execution pass. Provider implementations must still reserve the tag and define how it
would normalize if enabled later.

