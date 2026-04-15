---
id: glossary-canonical-prompt
title: Canonical Prompt
type: glossary_term
status: current
summary: Standardized prompt tag that triggers specific workflow jobs in AUDiaGentic, config-managed and routed through a bridge for normalization
owners:
- core-team
updated_at: '2026-04-15'
tags:
- glossary
- prompts
- workflow
- agents
related:
- system-planning
---

## Summary
A **canonical prompt** is a standardized prompt tag that triggers a specific workflow job in the AUDiaGentic system. These prompts are config-managed, route through a bridge for normalization, and preserve provenance through the workflow. They provide a consistent interface for agents to initiate planning and implementation work.

## Current state
**Canonical Prompt Tags:**

| Tag | Skill | Description |
|-----|-------|-------------|
| `@ag-plan` | ag-plan | Create planning artifacts (requests, specs, plans) |
| `@ag-implement` | ag-implement | Execute implementation work |
| `@ag-review` | ag-review | Review work and call out gaps |
| `@ag-audit` | ag-audit | Audit system state and compliance |
| `@ag-check-in-prep` | ag-check-in-prep | Prepare for check-in/commit |

**Provider Shorthands:**
- `cx` → codex
- `cld` → claude
- `cln` → cline
- `gm` → gemini
- `opc` → opencode
- `cp` → copilot

**Prompt Syntax:**
```text
@ag-review provider=codex id=job_001 ctx=documentation t=review-default
Review the current project state and call out any gaps.
```

**Short Form (with defaults):**
```text
@ag-review
```

**Long Form (explicit):**
```text
@ag-review
provider=codex
id=job_001
context=documentation
output=docs/review.md
template=review-default
```

**Bridge Mechanics:**
1. Raw prompt read (tag + body)
2. Tag normalized using `.audiagentic/prompt-syntax.yaml`
3. Provider shorthand resolved
4. Provenance preserved (provider id, surface, session id)
5. Project defaults applied for missing fields
6. Job created with normalized contract
7. Output streamed through AUDiaGentic runtime

**Configuration:**
- Prompt syntax: `.audiagentic/prompt-syntax.yaml`
- Agent instructions: `AGENTS.md`
- Bridge implementation: `tools/codex_prompt_trigger_bridge.py`

## How to use
**Using Canonical Prompts:**

1. **Start prompt with tag**: `@ag-plan`, `@ag-implement`, etc.
2. **Add optional parameters**: `provider=`, `id=`, `ctx=`, `t=`
3. **Include prompt body**: Detailed instructions after the tag line
4. **Submit through bridge**: Prompt routed to workflow job

**Example Prompts:**

```text
@ag-plan
Create a specification for adding MCP server support to the knowledge component.

---

@ag-implement provider=codex id=impl_001
Implement the event adapter configuration for planning events.

---

@ag-review ctx=knowledge
Review the current knowledge vault state and identify gaps.
```

**For Agents:**
- Do not reinterpret canonical tags
- Route tagged prompts through the bridge
- Preserve provenance fields
- Keep canonical names from config

**For Humans:**
- Use tags to trigger specific workflows
- Provide context in the prompt body
- Optional: specify provider and job ID

## Sync notes
This page should be refreshed when:
- New canonical tags are added
- Tag meanings change
- Bridge mechanics are modified
- Provider shorthands are updated

**Sources:**
- `.audiagentic/prompt-syntax.yaml` - Prompt syntax configuration
- `AGENTS.md` - Agent instructions
- `tools/codex_prompt_trigger_bridge.py` - Bridge implementation

**Sync frequency:** On prompt syntax or bridge changes

## References
- [AGENTS.md](../../../AGENTS.md)
- [Prompt Syntax Config](../../../.audiagentic/prompt-syntax.yaml)
- [Planning System](../systems/system-planning.md)
