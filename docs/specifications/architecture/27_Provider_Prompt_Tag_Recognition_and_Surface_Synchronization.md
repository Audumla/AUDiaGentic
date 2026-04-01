# Provider Prompt-Tag Recognition and Surface Synchronization

## Purpose

Freeze the provider-facing part of the `.2` extension so every supported provider surface can recognize the same prompt tags, normalize them consistently, and dispatch the same `PromptLaunchRequest` contract into the jobs layer.

This document exists because the core `.2` prompt-launch extension defines **what** must be launched, but teams also need a synchronized rule set for **how each provider surface participates** without duplicating the whole prompt-launch design in every provider document.

## Relationship to existing docs

This document is additive. It does not replace:
- `24_DRAFT_Provider_Model_Catalog_and_Selection.md`
- `26_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md`
- provider-specific plans under `docs/implementation/providers/`
- the Phase 4.4 provider execution compliance model and provider-specific implementation docs

Read it as the provider-surface companion to the Phase 3.2 prompt-launch extension and the shared surface half of the Phase 4.4 provider execution layer.

## Design intent

The original requirement was not only that jobs could be launched from tagged prompts, but that the provider entry surfaces used by developers — CLI tools and VS Code extensions — could participate in that flow predictably.

The desired end functionality is broader: every supported provider surface, whether CLI-backed, editor-backed, or bridge-backed, must converge on the same canonical prompt-entry contract and the same repo-owned launch path.

That means:
1. the same tag syntax must work across supported providers
2. provider surfaces must not invent provider-specific tag semantics
3. provider-specific settings must be kept in sync with the canonical prompt-launch grammar
4. differences between providers must be isolated to thin surface adapters, not pushed into the jobs core

This is the user-facing end-state, not just a stopgap implementation note.

## Scope

This document freezes:
- the provider-surface contract for prompt-tag recognition
- tracked provider config fields for prompt-tag surface behavior
- provider descriptor additions for prompt-tag capability reporting
- synchronization rules between shared docs and provider-specific implementation docs
- the Phase 4.3 packet sequence for provider-surface rollout

## Out of scope

- redefining prompt syntax already frozen in `.2`
- natural-language routing without tags
- vendor-specific GUI walkthroughs for every third-party product revision
- automatic cross-provider failover
- cross-provider prompt rewriting

## Core design decision

The system uses a **shared parser contract with provider-specific surface adapters**.

That means:
- the canonical grammar remains `prefix-token-v1`
- every surface must present the same first-line tag grammar to the user
- every surface must normalize into the same `PromptLaunchRequest`
- provider-specific configuration only controls **how the surface recognizes and forwards the prompt**, not **what the tags mean**

## Canonical surface rule

Every supported interactive provider surface must obey this rule:

> Parse or preserve the first non-empty line exactly according to `prefix-token-v1`, then normalize to `PromptLaunchRequest`, then forward the prompt body and normalized launch request into the jobs core.

A provider surface may implement that rule in one of four modes:
- `native-pass-through`
- `wrapper-normalize`
- `extension-normalize`
- `bridge-wrapper`

`unsupported` may be declared for a surface that the project chooses not to wire into prompt launch.

### Mode meanings

#### `native-pass-through`
The provider surface can preserve the tag line unchanged and pass it directly to the AUDiaGentic launcher without local reinterpretation.

#### `wrapper-normalize`
A CLI wrapper owned by AUDiaGentic reads the first line, builds `PromptLaunchRequest`, and then invokes the provider CLI with the prompt body and normalized launch metadata.

#### `extension-normalize`
A VS Code extension integration owned by AUDiaGentic reads the first line, builds `PromptLaunchRequest`, and then invokes the provider-facing extension path.

#### `bridge-wrapper`
Use this when the provider does not expose a first-class prompt-tag aware interactive surface. AUDiaGentic supplies the tag-aware bridge and then talks to the provider through an OpenAI-compatible or similar adapter.

## Additive ProviderConfig fields (Phase 4.3)

Provider prompt-surface configuration lives in `.audiagentic/providers.yaml` under each provider entry.

```yaml
contract-version: v1
providers:
  codex:
    enabled: true
    install-mode: external-configured
    access-mode: cli
    default-model: gpt-5.4-mini
    prompt-surface:
      enabled: true
      tag-syntax: prefix-token-v1
      first-line-policy: first-non-empty-line
      cli-mode: wrapper-normalize
      vscode-mode: extension-normalize
      settings-profile: codex-prompt-tags-v1
```

### Rules

- `prompt-surface` is optional.
- if `prompt-surface.enabled` is `false` or omitted, the provider is not considered part of the prompt-tag launch surface matrix
- when enabled, `tag-syntax` must be `prefix-token-v1`
- when enabled, `first-line-policy` must be `first-non-empty-line`
- when enabled, at least one of `cli-mode` or `vscode-mode` must be present and must not be `unsupported`
- provider surface config does not change tag meaning; it only declares supported surface handling
- `settings-profile` identifies the provider-specific settings bundle/checklist that must be kept aligned with the shared rules

## Additive ProviderDescriptor fields (Phase 4.3)

Providers report prompt-tag capability through additive descriptor fields.

```json
{
  "contract-version": "v1",
  "provider-id": "codex",
  "install-mode": "external-configured",
  "supports-jobs": true,
  "supports-interactive": true,
  "supports-skill-wrapper": true,
  "supports-structured-output": true,
  "supports-server-session": false,
  "supports-baseline-healthcheck": true,
  "supports-prompt-tag-launch": true,
  "prompt-tag-syntaxes": ["prefix-token-v1"],
  "prompt-tag-cli-mode": "wrapper-normalize",
  "prompt-tag-vscode-mode": "extension-normalize",
  "requires-surface-settings-sync": true
}
```

### Rules

- `supports-prompt-tag-launch` means the provider may participate in the shared prompt-launch flow when configured
- `prompt-tag-syntaxes` is additive and should contain `prefix-token-v1` in MVP
- `prompt-tag-cli-mode` and `prompt-tag-vscode-mode` describe the normalized surface mode, not vendor marketing names
- `requires-surface-settings-sync` must be `true` for any provider whose prompt-tag behavior relies on external wrapper or extension settings

## Provider coverage matrix for MVP

| Provider id | CLI surface mode | VS Code surface mode | Notes |
|---|---|---|---|
| `codex` | `wrapper-normalize` | `extension-normalize` | first-class interactive provider; must keep wrapper + VS Code settings in sync |
| `claude` | `wrapper-normalize` | `extension-normalize` | same prompt grammar as codex; provider-specific settings handled in provider doc |
| `gemini` | `wrapper-normalize` | `extension-normalize` | same shared grammar; provider doc defines profile/checklist |
| `copilot` | `bridge-wrapper` or provider-specific CLI bridge | `extension-normalize` | VS Code-first integration is expected; CLI path may be bridge-owned |
| `continue` | `wrapper-normalize` | `extension-normalize` | same shared normalization rule |
| `cline` | `wrapper-normalize` | `extension-normalize` | same shared normalization rule |
| `local-openai` | `bridge-wrapper` | `bridge-wrapper` | AUDiaGentic owns the tag-aware bridge; provider itself remains OpenAI-compatible |
| `qwen` | `bridge-wrapper` | `bridge-wrapper` | same as `local-openai`; no separate native surface contract required in MVP |

This matrix is intentionally about **AUDiaGentic integration mode**, not about external product branding.

## Synchronization doctrine

To avoid duplication, prompt-tag surface behavior is split into two layers.

### Shared layer
Owned centrally and updated once:
- canonical grammar
- normalization rules
- tracked config fields
- descriptor fields
- verification matrix
- common recovery rules

### Provider-specific delta layer
Owned in each provider plan:
- which surface modes are used for that provider
- which settings profile name is used
- which wrapper/extension entry point is responsible
- provider-specific smoke tests or setup steps
- provider-specific limitations

Provider docs must not restate the full grammar. They must reference this doc and only record provider-specific deltas.

## Shared verification matrix

Every provider participating in prompt-tag launch must prove the same minimum behaviors.

### Contract validation
- provider config with `prompt-surface` validates
- provider descriptor advertises the correct prompt-tag capability

### Unit behavior
- first-line parsing is invoked exactly once at the surface boundary
- unknown tags fail before provider dispatch
- duplicate directives fail before provider dispatch
- provider-specific settings profile is loaded for the selected surface

### Integration behavior
- `@plan` launches a packet target through the provider surface
- `@implement` resumes or advances a legal job target through the provider surface
- `@review` forwards a review-capable launch request and preserves reviewer provenance
- prompt body reaches the jobs core without the tag line duplicated into the body

### Regression behavior
- provider surface changes do not bypass the shared jobs validation path
- provider surface changes do not write tracked docs directly
- provider surface changes do not reinterpret tag semantics

## Shared rollout sequence (Phase 4.3)

Phase 4.3 begins only after `.2` core packets are verified.

Packet order:
1. `PKT-PRV-014` — shared prompt-tag surface contract, schema, and sync harness
2. `PKT-PRV-015` — codex prompt-tag surface integration
3. `PKT-PRV-016` — claude prompt-tag surface integration
4. `PKT-PRV-017` — gemini prompt-tag surface integration
5. `PKT-PRV-018` — copilot prompt-tag surface integration
6. `PKT-PRV-019` — continue prompt-tag surface integration
7. `PKT-PRV-020` — cline prompt-tag surface integration
8. `PKT-PRV-021` — local-openai/qwen bridge-wrapper prompt-tag integration

## Change-control rule

Any change to prompt-tag surface behavior must update all of the following together:
- this architecture doc
- `03_Common_Contracts.md`
- relevant schemas and fixtures
- `38_Phase_4_3_Provider_Prompt_Tag_Surface_Integration.md`
- `docs/implementation/providers/10_Prompt_Tag_Surface_Integration_Shared.md`
- the affected provider plan doc(s)
- the build-status registry and dependency graph if packet scope changes

## Completion rule

The original requirement is not considered fully restored until:
- `.2` job-side prompt launch is verified, and
- `.2` provider-surface integration is verified for every enabled provider surface in the project configuration

The end-state described by this document is not considered complete until:
- every supported provider surface documents the mechanics it uses to reach the shared bridge
- provider docs stop defining alternate semantics and instead describe concrete normalization mechanics only
- all prompt-entry surfaces funnel into the same canonical `PromptLaunchRequest` contract
