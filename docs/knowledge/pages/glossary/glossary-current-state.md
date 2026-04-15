---
id: glossary-current-state
title: Current State
type: glossary_term
status: current
summary: Documentation describing how a system works now, not how it should work; observational, factual, and focused on present operational reality
owners:
- core-team
updated_at: '2026-04-15'
tags:
- glossary
- documentation
- terminology
related:
- system-knowledge
- pattern-page-lifecycle
---

## Summary
**Current state** documentation describes how a system, process, or component works *now*, not how it should work or how it was designed to work. It is observational, factual, and focused on the present operational reality. Current-state docs are the primary content type in the knowledge vault.

## Current state
**Characteristics of Current-State Documentation:**

| Aspect | Current State | NOT Current State |
|--------|---------------|-------------------|
| Tense | Present ("does", "is", "has") | Future ("will", "should", "must") |
| Focus | Operational reality | Requirements or goals |
| Content | What exists and how it works | What should exist |
| Updates | When system changes | When requirements change |
| Audience | Anyone needing to understand the system | Stakeholders defining requirements |

**Examples:**

✅ **Current State:**
- "The planning system stores tasks in `docs/planning/tasks/`"
- "Tasks flow through states: draft → ready → in_progress → done"
- "The knowledge component uses YAML for configuration"

❌ **NOT Current State:**
- "Tasks should be stored in a database" (requirement)
- "The system will support real-time collaboration" (future goal)
- "Users must be able to search by date" (requirement)

**Page Structure:**
All current-state pages follow a standard template:
```markdown
## Summary
Brief overview of what this documents.

## Current state
Detailed description of how it works now.

## How to use
Instructions for humans or agents.

## Sync notes
How and when this page should be updated.

## References
Links to related documentation.
```

**Relationship to Other Docs:**
- **Drafts/Proposals**: Incomplete work, not yet current state
- **Specifications**: Requirements for future work
- **Decisions**: Rationale for past choices (ADR format)
- **Current State**: Operational documentation (knowledge vault)

## How to use
**Writing Current-State Content:**

1. **Use present tense**: "The system does X" not "The system will do X"
2. **Be factual**: Describe what exists, not what should exist
3. **Include operational details**: Paths, commands, configurations
4. **Note limitations**: Document known constraints or quirks
5. **Link to sources**: Reference code, configs, or artifacts

**Maintaining Current State:**

1. **Mark sync sources**: Document what triggers updates
2. **Use event-driven updates**: Let events mark pages stale
3. **Review proposals**: Check `docs/knowledge/proposals/` regularly
4. **Update promptly**: Keep docs synchronized with reality

**When NOT to Update:**
- Speculative changes (not implemented)
- Draft work (not verified)
- Future plans (not current reality)

## Sync notes
This page is meta-documentation about the current-state concept itself. It should be refreshed when:
- Knowledge vault conventions change
- Page templates are modified
- Sync processes are updated

**Sources:**
- Knowledge component design documents
- Page templates in `docs/knowledge/templates/`
- Sync configuration in `docs/knowledge/sync/`

**Sync frequency:** On knowledge vault convention changes

## References
- [Knowledge System](../systems/system-knowledge.md)
- [Glossary: Artifact](./glossary-artifact.md)
- [Pattern: Page Lifecycle](../patterns/pattern-page-lifecycle.md)
