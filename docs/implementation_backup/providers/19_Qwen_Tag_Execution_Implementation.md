# Qwen Code tag execution implementation

Provider: Qwen Code terminal + VS Code companion  
Compliance level: A* — native intercept with experimental hooks  
Execution state: IMPLEMENTED
Phase: 4.4

## Confirmation summary

Qwen Code documents:
- project/user configuration via `.qwen/settings.json`
- hook support including `UserPromptSubmit`
- hook configuration in project settings
- permissions and tool-related hook events

The official hook docs currently mark hooks as an experimental feature that requires the
`--experimental-hooks` flag. Because of that, Qwen qualifies as native-intercept capable,
but rollout should remain guarded. The CLI-backed execution wrapper is live and smoke-tested;
the hook-native path remains a follow-on concern if the provider surface shifts upstream.

## Related docs

- `docs/specifications/architecture/28_Provider_Tag_Execution_Compliance_Model.md`
- `docs/implementation/providers/11_Provider_Tag_Execution_Conformance_Matrix.md`

## Native assets to use

### Settings
Use:
- `.qwen/settings.json`

Purpose:
- enable and wire hook execution
- store project-level policy
- keep the implementation under version control

### Hooks
Required:
- `UserPromptSubmit`

Recommended:
- `PreToolUse`
- `PermissionRequest`
- `PostToolUse` for audit / telemetry enrichment

## Hook implementation strategy

### UserPromptSubmit
Responsibilities:
- inspect raw prompt
- detect canonical first-line tag
- reject unsupported tags
- inject normalized launch metadata

### PreToolUse / PermissionRequest
Responsibilities:
- restrict implementation power by stage
- keep review mode read-focused unless explicitly elevated
- preserve policy consistency

## CLI path

1. launch Qwen with `--experimental-hooks`
2. user submits raw prompt
3. `UserPromptSubmit` hook detects the canonical tag
4. Qwen proceeds with normalized context and policy restrictions

## VS Code path

Use the same `.qwen/settings.json` and shared hook scripts where the VS Code companion
supports the project configuration. The repository should own the behavior, not a separate
editor-only implementation.

## Exact files/settings to plan for later implementation

Repo files:
- `.qwen/settings.json`
- hook scripts
- optional repo guidance doc describing canonical tag doctrine

Runtime requirements:
- Qwen launched with experimental hooks enabled until the feature is no longer marked experimental

## Risks / limits

- hooks are explicitly marked experimental in the current official Qwen docs
- rollout must be feature-flagged
- completion criteria should include a fallback plan if the hook surface changes upstream

## Recommendation

Document Qwen as native-intercept capable and wrapper-implemented.
Keep the experimental hook path feature-gated until the native-intercept smoke tests are
validated against the same canonical prompts and provider constraints as the other providers.

## Related docs

- `docs/implementation/providers/27_Qwen_Prompt_Trigger_Runbook.md`




