# Phase 4.3 — Provider Prompt-Tag Surface Integration

## Purpose

This is the execution-ready guide for the provider-facing half of the `.2` extension.
It defines how each provider CLI or VS Code integration must recognize the canonical prompt tags and hand work into the already-frozen jobs launch path.

## Why Phase 4.3 exists

Phase 3.2 restored prompt-driven launch at the jobs layer, but the original requirement was broader:
- developers should be able to use their chosen provider surface
- the same tags should work across supported providers
- provider-specific settings should be synchronized rather than drifting independently

This phase closes that gap.

## Hard dependency rule

Phase 4.3 must not begin until all of the following are verified:
- `PKT-PRV-012`
- `PKT-FND-009`
- `PKT-LFC-009`
- `PKT-RLS-010`
- `PKT-JOB-008`
- `PKT-JOB-009`

That dependency is intentional. Provider surfaces should consume a frozen prompt-launch contract, not define one.

## Shared implementation rule

Every provider surface adapter must do exactly this:
1. detect the first non-empty line
2. parse or preserve it as `prefix-token-v1`
3. normalize to `PromptLaunchRequest`
4. remove the tag line from the prompt body before provider dispatch when needed
5. forward normalized launch metadata to the jobs core
6. preserve provider/surface/session provenance

No provider adapter may:
- reinterpret tag semantics
- bypass jobs validation
- write review bundles directly
- write tracked docs directly

## Shared ownership split

Phase 4.4 defines the provider execution compliance model and the isolated provider implementation docs that sit on top of this shared surface contract.

### Shared surface contract packet
`PKT-PRV-014` owns:
- shared provider config/descriptor schema updates
- shared verification harness for prompt-tag surfaces
- shared sync matrix and settings-profile rules
- common provider-facing adapter contract docs

### Per-provider rollout packets
Provider rollout packets own only their provider-specific delta:
- chosen surface modes
- provider-specific settings profile/checklist
- wrapper/extension entry points
- provider-specific tests and notes

## Packet sequence

### PKT-PRV-014
Shared prompt-tag surface contract, config schema, provider descriptor capability fields, shared verification matrix, and synchronization doctrine.

### PKT-PRV-015
Codex surface rollout.

### PKT-PRV-016
Claude surface rollout.

### PKT-PRV-017
Gemini surface rollout.

### PKT-PRV-018
Copilot surface rollout.

### PKT-PRV-019
Continue surface rollout.

### PKT-PRV-020
Cline surface rollout.

### PKT-PRV-021
local-openai / qwen bridge-wrapper rollout.

## Required artifacts

### Shared tracked artifacts
- additive ProviderConfig fields under `.audiagentic/providers.yaml`
- additive ProviderDescriptor capability fields
- provider implementation docs under `docs/implementation/providers/`

### Runtime-only artifacts
- optional launch traces under `.audiagentic/runtime/providers/<provider-id>/prompt-launch/`
- provider-surface test captures and smoke-test output under runtime or test temp paths only

## Required provider settings discipline

Each participating provider must define one `settings-profile` name.
That profile acts as the canonical checklist bundle for:
- CLI wrapper behavior
- VS Code adapter behavior
- preserved surface/session identifiers
- smoke-test commands
- rollback/recovery steps

The settings profile name is tracked in `.audiagentic/providers.yaml`.
The actual third-party settings path may vary by environment and is documented only in the provider-specific plan doc.

## Shared acceptance matrix

A provider rollout is not complete until all of the following pass:
- schema validation for provider config/descriptor changes
- provider surface accepts `@plan`, `@implement`, and `@review`
- launch request reaches the same `PromptLaunchRequest` shape as every other provider
- prompt body reaches the jobs core without duplicated tag line
- provenance includes provider id, surface, and session key
- provider-specific settings profile is documented and synchronized

## Shared recovery rule

If a provider rollout fails mid-implementation:
- revert only the provider-specific surface adapter files
- keep the shared contract packet untouched unless the contract itself is wrong
- disable the provider’s `prompt-surface.enabled` flag if needed
- rerun shared prompt-surface contract tests and the provider-specific integration suite

## Completion rule

The prompt-launch requirement is not fully satisfied until the shared packet and every enabled provider rollout packet are verified.
The provider execution layer is then documented separately in Phase 4.4 so each provider can be implemented and tested in isolation.
