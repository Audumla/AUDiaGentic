# Draft Provider Prompt-Trigger Launch Behavior

Status: draft
Phase: 4.5
Feature slot: .6

## Purpose

This spec defines how a provider-owned prompt surface can turn a tagged prompt into a real
AUDiaGentic launch request. It is the behavior layer that sits above the existing prompt-tag
grammar and the existing prompt-launch contract.

The goal is not to change the canonical launch grammar. The goal is to make provider-local
instruction surfaces, wrappers, hooks, and bridge commands all converge on the same launch
entry point with the same provenance.

This is the intended end functionality for all supported providers: every CLI or prompt-entry
surface should be able to accept the canonical workflow syntax and reach the same repo-owned
bridge/launcher path, even if the concrete mechanics vary by provider.

## Problem statement

Phase 3.2 defined how a prompt can be parsed into a normalized launch request.
Phase 4.3 defined how provider surfaces can recognize the canonical tags.
This feature defines how those provider surfaces actually launch the workflow runner.

In practice, that means the first-line tag or provider shorthand must be able to:
- select the launch action
- preserve provider and surface provenance
- choose the configured default model when the prompt omits one
- invoke the shared launcher or bridge in a way that can be tested independently

## Normative rules

- the canonical grammar remains `prefix-token-v1`
- provider-local instructions must not invent alternate tag meanings
- a provider may use a native instruction surface, a hook, a wrapper, or a bridge command
- if a provider cannot intercept raw prompts reliably, a repo-owned wrapper must be used
- all trigger paths must normalize into the same `PromptLaunchRequest` shape used by Phase 3.2
- the launcher must preserve `source.surface`, `source.provider-id`, and session provenance when available
- `@adhoc` stays feature-gated in the first launch path unless a provider packet explicitly enables it

## Trigger model

The prompt-trigger path has four common steps:

1. detect a canonical tag or provider shorthand in the first non-empty line
2. resolve provider defaults and the applicable launch action
3. call the shared launcher or bridge with normalized metadata
4. persist the resulting job, review, and provenance records as usual

## Surface classes

### Native instruction surface

The provider exposes a local instruction file, hook surface, or equivalent prompt-submit
interception point that can normalize the prompt before the provider begins planning.

### Bridge-wrapper surface

The provider does not expose a stable pre-submit hook, so a repo-owned wrapper captures the
tagged prompt and calls the shared launcher directly.

### Backend-only surface

The provider is only a model/backend endpoint. In that case the prompt-trigger behavior lives
entirely in the repo-owned wrapper or bridge layer above the backend.

## Shared launch contract

The prompt-trigger behavior must feed the existing prompt-launch contract, not a new one.
Required launch metadata remains:
- `launch-tag`
- `launch-target`
- `launch-source`
- `provider-id`
- `model-id` or `model-alias` when relevant
- review policy and session provenance when available

## Provider coverage matrix

| Provider | Trigger surface strategy | Primary local assets | Fallback path |
|---|---|---|---|
| Codex | wrapper-normalize + AGENTS.md guidance | `AGENTS.md`, optional repo skills, wrapper script | shared repo bridge |
| Claude | hook or instruction-file normalization | `CLAUDE.md`, `.claude/rules`, `.claude/skills` | shared repo bridge |
| Gemini | instruction-file or command-template normalization | `GEMINI.md`, command templates | shared repo bridge |
| GitHub Copilot | instruction-file / custom agent normalization | `.github/copilot-instructions.md`, custom agents | shared repo bridge |
| Continue | config-driven invocation normalization | `config.yaml`, rules, invokable prompts | shared repo bridge |
| Cline | hook / rules / workflow normalization | `.clinerules`, hooks, workflows | shared repo bridge |
| local-openai / qwen | bridge-wrapper only | repo bridge, provider config, model catalog | same repo bridge |

Realistic rollout note:
- Claude and Cline are the strongest first-wave candidates for hook-backed rollout.
- Codex, Copilot, Continue, and local-openai should be treated as wrapper/bridge-first.
- Gemini and Qwen should remain guarded until their fallback paths and hook behavior are validated locally.

## Acceptance expectations

- each provider has a documented trigger surface and fallback bridge path
- the canonical grammar still parses the same way everywhere
- launch provenance remains visible to the jobs layer
- the bridge/wrapper can be smoke-tested without editing the shared launch contract
- provider-specific instructions stay isolated from shared grammar docs
- the end-state is clearly documented as the same across all supported providers and all CLI/prompt-entry surfaces

## Non-goals

- redefining the canonical prompt grammar
- introducing provider-specific alternate tags
- coupling provider execution adapters to prompt-trigger behavior
- changing the review bundle or approval contracts unless the launch envelope itself changes
