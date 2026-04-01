# Draft Canonical Prompt Entry and Bridge End State

Status: draft
Phase: 4.13
Feature slot: .13

## Purpose

This spec states the desired end functionality for **all supported providers** and **all CLI or prompt-entry surfaces** in AUDiaGentic.

The end-state is intentionally simple:

- a user may type a canonical workflow tag or provider shorthand into a supported prompt-entry surface
- the surface normalizes the prompt into the repo-owned bridge
- the bridge creates the `PromptLaunchRequest`
- AUDiaGentic owns provenance, defaults, capture, persistence, and downstream job lifecycle handling
- provider-specific mechanics only describe how the surface reaches the bridge, not what the workflow means

This is the authoritative statement of the desired end functionality the user asked for: every supported provider should converge on the same canonical bridge/launcher path, regardless of whether the surface is a CLI, editor integration, or prompt-entry wrapper.

## Relationship to existing docs

This document is additive. It does not replace:
- `03_Common_Contracts.md`
- `26_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md`
- `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`
- `29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- provider-specific implementation docs under `docs/implementation/providers/`

Read it as the end-state guarantee for the prompt-calling layer across every supported provider.

## End-state guarantee

When the feature set is complete, the following must be true:

1. A prompt beginning with a canonical workflow tag or provider shorthand can be launched from any supported provider surface.
2. All supported provider surfaces normalize the same canonical grammar before the jobs layer sees the request.
3. All supported provider surfaces preserve provenance fields such as provider id, surface, and session id.
4. All supported provider surfaces forward into the same repo-owned bridge or launcher contract.
5. Provider-specific hooks, wrappers, and instruction files are implementation details only; they may vary, but they may not redefine the workflow semantics.
6. AUDiaGentic owns output capture, runtime artifacts, review records, and job persistence.
7. The same prompt-entry contract applies to CLI entry, editor entry, and future surface adapters.

## Canonical runtime contract

The bridge/launcher contract is the same one already defined by Phase 3.2 and the shared provider-surface docs:

- canonical grammar remains `prefix-token-v1`
- `@plan`, `@implement`, `@review`, `@audit`, and `@check-in-prep` remain the canonical workflow selectors
- provider shorthand may select the provider default behavior, but it does not change the canonical grammar
- `@adhoc` remains the generic agent-call baseline and may be feature-gated as previously defined
- defaults for target, model, context, output, template, stream controls, and input controls are merged by AUDiaGentic when omitted

## Supported provider classes

The end-state must be reachable through all supported providers, including:

- `codex`
- `claude`
- `gemini`
- `qwen`
- `copilot`
- `continue`
- `cline`
- `local-openai`

The mechanism for each provider may differ, but the end-state behavior must remain the same.

## Permitted implementation styles

A provider surface may use one or more of the following, as appropriate:

- native instruction files
- prompt-submit hooks
- wrapper-normalize CLI scripts
- extension-normalize editor integrations
- repo-owned bridge wrappers

The implementation style may vary per provider. The end-state may not vary.

## Explicit non-goals

- inventing per-provider alternate workflow semantics
- making the provider itself the owner of persistence policy
- requiring agents to manually write runtime artifacts
- duplicating the canonical grammar per provider doc
- coupling this end-state to any single future workflow engine or task tracker

## Expected usage shape

Users should be able to write prompts in a compact, defaults-first form such as:

```text
@review provider=cline id=job_001 ctx=documentation t=review-default
Review the current project state and call out any gaps.
```

or the equivalent long form:

```text
@review provider=cline id=job_001 context=documentation template=review-default
Review the current project state and call out any gaps.
```

The chosen provider surface is responsible for getting that prompt to the bridge; the bridge is responsible for normalizing it into the shared launch contract.

## Completion rule

This end-state is not considered fully achieved until:

- every supported provider has a documented prompt-entry path that routes to the shared bridge or launcher
- provider docs state the same canonical behavior instead of redefining it
- the shared launch contract is the single authoritative workflow grammar
- bridge-owned capture and persistence remain AUDiaGentic responsibilities
