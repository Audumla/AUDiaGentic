# GitHub Copilot tag execution implementation

Provider: GitHub Copilot CLI + VS Code agent mode  
Compliance level: B — mapped execution via thin adapter  
Execution state: NOT IMPLEMENTED
Phase: 4.4

## Confirmation summary

GitHub Copilot supports:
- repository-wide custom instructions via `.github/copilot-instructions.md`
- path-scoped instructions in `.github/instructions/**/*.instructions.md`
- `AGENTS.md` support
- prompt files
- custom agents (`.github/agents/*.agent.md`)
- agent skills (`SKILL.md`) usable with Copilot coding agent, Copilot CLI, and VS Code agent mode

What is not confirmed in the current docs is a deterministic pre-submit hook for arbitrary
custom first-line `@tag` parsing. Therefore canonical exact-tag UX should be documented
as adapter-based.

## Related docs

- `docs/specifications/architecture/28_Provider_Tag_Execution_Compliance_Model.md`
- `docs/implementation/providers/11_Provider_Tag_Execution_Conformance_Matrix.md`

## Native assets to use

### Instructions
Use:
- `.github/copilot-instructions.md`
- optional `.github/instructions/**/*.instructions.md`
- optional root `AGENTS.md`

Purpose:
- define canonical tag semantics
- define review rules
- define tracked-doc restrictions
- define packet/workflow mapping expectations

### Prompt files
Create prompt files for discoverable mapped execution:
- `.github/prompts/plan.prompt.md`
- `.github/prompts/implement.prompt.md`
- `.github/prompts/review.prompt.md`
- `.github/prompts/audit.prompt.md`
- `.github/prompts/check-in-prep.prompt.md`

### Custom agents / skills
Create:
- `.github/agents/planner.agent.md`
- `.github/agents/reviewer.agent.md`
- `.github/skills/.../SKILL.md` where richer delegation is needed

## Required adapter

The adapter is required for exact literal `@tag` compatibility across CLI and VS Code.

Responsibilities:
- parse canonical tag
- validate allowed tag
- build canonical request envelope
- choose the correct Copilot prompt file / agent / skill
- preserve raw prompt provenance

## CLI path

1. user enters raw prompt
2. wrapper normalizes canonical tag
3. wrapper invokes Copilot CLI with the chosen mapped asset
4. repository instructions and skills provide the stable behavior layer

## VS Code path

1. user enters raw prompt in Copilot chat / agent mode
2. extension bridge or command reroutes the prompt through the same normalizer
3. bridge invokes the selected prompt file / agent mode / skill path

## Exact files/settings to plan for later implementation

Repo files:
- `.github/copilot-instructions.md`
- `.github/instructions/...` as needed
- `.github/prompts/*.prompt.md`
- `.github/agents/*.agent.md`
- optional root `AGENTS.md`

Bridge files:
- CLI adapter
- VS Code adapter / command binding
- shared canonical normalizer

## Risks / limits

- no documented native raw custom tag interception found in current official material
- custom agents may be selected semantically, which is not deterministic enough by itself
- keep exact tag behavior in the wrapper, not in agent descriptions alone

## Recommendation

Implement Copilot as an adapter-based provider.
Use prompt files, custom agents, and skills as the destination surfaces, but keep exact
canonical tag parsing outside the provider runtime.

## Related docs

- `docs/implementation/providers/23_Copilot_Prompt_Trigger_Runbook.md`




