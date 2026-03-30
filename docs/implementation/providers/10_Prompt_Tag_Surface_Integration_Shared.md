# Shared Prompt-Tag Surface Integration Plan

## Purpose

Provide the shared checklist used by all provider-specific prompt-tag integration docs.
This file exists to minimize duplication: the grammar, normalization rules, and acceptance matrix are defined once here, while each provider doc records only its deltas.

## Shared rules all providers must inherit

- Canonical syntax: `prefix-token-v1`
- Parse location: first non-empty line only
- Normalized contract: `PromptLaunchRequest`
- Tags must keep the same meanings across providers
- Prompt body must exclude the tag line after normalization when the provider receives body text
- Provider adapters must preserve provider id, surface, and a stable session key

## Shared checklist template

Every provider-specific rollout doc must answer these questions:
1. Which surfaces are supported: `cli`, `vscode`, or both?
2. Which surface mode is used for each surface?
3. What is the `settings-profile` name?
4. Which wrapper or extension entry point performs normalization?
5. What smoke test proves `@plan` works?
6. What smoke test proves `@implement` works?
7. What smoke test proves `@review` works?
8. Which in-chat asset or hook receives the tags before the provider plans?
9. What is the rollback step if provider settings drift?

## Shared verification commands

Recommended minimum test targets:
- `tests/unit/contracts/test_schema_validation.py`
- `tests/unit/providers/test_prompt_surface_contract.py`
- `tests/integration/providers/test_prompt_surface_<provider-id>.py`
- prompt-launch regression tests under `tests/integration/jobs/`

## Shared provider matrix

| Provider | Primary packet | CLI mode | VS Code mode | Settings profile |
|---|---|---|---|---|
| codex | `PKT-PRV-014` | `wrapper-normalize` | `extension-normalize` | `codex-prompt-tags-v1` |
| claude | `PKT-PRV-015` | `wrapper-normalize` | `extension-normalize` | `claude-prompt-tags-v1` |
| gemini | `PKT-PRV-016` | `wrapper-normalize` | `extension-normalize` | `gemini-prompt-tags-v1` |
| copilot | `PKT-PRV-017` | `bridge-wrapper` or project bridge | `extension-normalize` | `copilot-prompt-tags-v1` |
| continue | `PKT-PRV-018` | `wrapper-normalize` | `extension-normalize` | `continue-prompt-tags-v1` |
| cline | `PKT-PRV-019` | `wrapper-normalize` | `extension-normalize` | `cline-prompt-tags-v1` |
| local-openai / qwen | `PKT-PRV-021` | `bridge-wrapper` | `bridge-wrapper` | `openai-bridge-prompt-tags-v1` |

## Duplication rule

Provider docs must not restate the complete grammar or jobs behavior. They should reference:
- `26_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md`
- `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`
- `38_Phase_4_3_Provider_Prompt_Tag_Surface_Integration.md`
- `39_Phase_4_4_Provider_Tag_Execution_Implementation.md`

Then document only provider-specific surface choices, settings profiles, and verification details.
Phase 4.4 adds separate provider execution docs; keep those isolated and do not collapse them back into this shared surface file.
