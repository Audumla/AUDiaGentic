# Provider Prompt Templates and Defaults

**Status:** VERIFIED  
**Applies to:** All providers during prompt-trigger launches

---

## Principle

**Use shared default prompts unless a provider has material constraints or optimizations.**

This avoids unnecessary duplication while allowing provider-specific variants when justified.

---

## Architecture

### Shared Defaults

Location: `.audiagentic/prompts/<action>/default.md`

Available for all action types:
- `plan` — implementation planning
- `implement` — code/doc writing
- `review` — structured review (JSON output)
- `audit` — audit/drift detection
- `check-in-prep` — release artifact prep

**Applies to:** All providers unless a provider-specific variant exists.

### Provider-Specific Variants

Location: `.audiagentic/prompts/<action>/<provider>.md`

Created **only when:**
1. Provider has read-only/safety constraints (e.g., Cline in editor can't mutate)
2. Provider output format differs materially (e.g., abbreviated vs. structured)
3. Provider has known strengths/weaknesses worth optimizing for
4. Provider framework (editor, CLI, web) imposes different expectations

**Current state:**
- `review/cline.md` — JUSTIFIED (read-only emphasis, workspace awareness, no file schema detail)
- `review/claude.md` — DELETED (cosmetic differences only)
- Plan/implement/audit/check-in-prep claude variants — DELETED (no material difference)

---

## Template Variables

All templates use standard substitution variables:

- `{{id}}` — job/subject identifier
- `{{context}}` — context pack name or description
- `{{output}}` — output format directive
- `{{body}}` — user-supplied prompt body

---

## Bridge Behavior

When a prompt is triggered with a provider:

1. Check for `<action>/<provider>.md`
2. If found, use it; otherwise fall back to `<action>/default.md`
3. Substitute template variables with runtime values
4. Pass result to provider

---

## Adding Provider-Specific Templates

**Before creating a provider variant, ask:**

1. Does this provider have a safety/read-only constraint?
2. Does the output format differ from the default?
3. Would different instructions meaningfully improve results?

If "no" to all: use default.

**If yes, document why:**
- Add comment in PR explaining the constraint
- Update this spec with the provider and justification

---

## Current Inventory

| Action | Default | Variants | Notes |
|--------|---------|----------|-------|
| plan | ✅ | none | All providers use default |
| implement | ✅ | none | All providers use default |
| review | ✅ | cline | Cline: read-only + workspace constraints |
| audit | ✅ | none | All providers use default |
| check-in-prep | ✅ | none | All providers use default |

---

## Future Additions

When adding a new provider, start with defaults. Add a variant only if:
- The provider lacks full mutation capabilities (like Cline)
- The provider has a significantly different output format
- Testing shows the default underperforms for that provider

---

## Related Files

- `.audiagentic/prompts/` — template directory
- `src/audiagentic/execution/jobs/prompt_templates.py` — loader logic
- `PKT-PRV-033` — Claude baseline (uses defaults)
- `PKT-PRV-037` — Cline baseline (has review variant)
