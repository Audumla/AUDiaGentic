# Centralized Prompt Syntax and Aliases

**Status:** VERIFIED  
**Applies to:** All providers (Claude, Cline, Codex, Gemini, Copilot, Continue, local-openai, Qwen)

---

## Overview

Prompt tag syntax and aliases are centralized in `.audiagentic/prompt-syntax.yaml` and shared across all provider implementations. This ensures consistent tag handling across CLI, VS Code, and provider-specific surfaces without duplicating alias definitions.

---

## Configuration File

**Location:** `.audiagentic/prompt-syntax.yaml`

### Tag Aliases

Map shorthand tags to canonical actions:

```yaml
tag-aliases:
  p: plan
  i: implement
  r: review
  a: audit
  c: check-in-prep
```

Usage: `@p` expands to `@plan`

### Provider Aliases

Map shorthand provider names to canonical provider IDs:

```yaml
provider-aliases:
  cln: cline
  cld: claude
  cx: codex
  gm: gemini
  cp: copilot
```

Usage: `@plan provider=cln` expands to `@plan provider=cline`

### Combined Aliases

Direct tag+provider combinations for convenience:

```yaml
combined-aliases:
  r-cln: review provider=cline
  i-cld: implement provider=claude
  p-cx: plan provider=codex
```

Usage: `@r-cln` directly expands to `@review provider=cline`

---

## Syntax Examples

All of these are equivalent and resolve to the same request:

```
@review provider=cline
@r provider=cline
@r-cline
@r-cln
```

---

## How Aliases Work

1. **Prompt Parser** (`src/audiagentic/jobs/prompt_parser.py`)
   - Loads `.audiagentic/prompt-syntax.yaml` at startup
   - Resolves tag aliases before bridge invocation
   - Resolves provider aliases from directives and suffixes

2. **Provider Bridges** (e.g., `tools/claude_prompt_trigger_bridge.py`)
   - Pass raw prompt to shared bridge
   - Shared bridge handles alias normalization
   - All providers see normalized canonical tags

3. **Hook Handlers** (e.g., `tools/claude_hooks.py`)
   - Detect tag tokens (any `@` prefix)
   - Delegate alias resolution to shared bridge
   - Focus on detection, not normalization

---

## Adding New Aliases

### Step 1: Update `.audiagentic/prompt-syntax.yaml`

```yaml
# Add tag alias
tag-aliases:
  new-shorthand: canonical-tag

# Add provider alias
provider-aliases:
  new-shorthand: provider-id

# Add combined alias
combined-aliases:
  t-p: tag provider=provider
```

### Step 2: No provider-specific changes needed

All providers automatically recognize new aliases through the shared parser.

### Step 3: Document in provider-specific instruction files (optional)

For discoverability, add to:
- `CLAUDE.md` (Claude instructions)
- `.clinerules/` (Cline rules)
- `AGENTS.md` (Codex agents)
- Provider-specific instruction surfaces

---

## Validation

**Contract:** `.audiagentic/prompt-syntax.yaml` conforms to `docs/schemas/prompt-syntax.schema.json`

**Validation happens at:**
- Bridge startup (when loading syntax)
- Prompt parser initialization
- JSON schema validation in CI/CD

---

## Related Files

- `src/audiagentic/jobs/prompt_parser.py` — Tag resolution logic
- `src/audiagentic/jobs/prompt_syntax.py` — Config loading
- `docs/schemas/prompt-syntax.schema.json` — Schema definition
- `tools/claude_hooks.py` — Hook-based tag detection
- `tools/claude_prompt_trigger_bridge.py` — Claude bridge
- `CLAUDE.md` — Claude-specific instructions

---

## Principles

1. **Centralized:** Single source of truth in `.audiagentic/prompt-syntax.yaml`
2. **Consistent:** All providers use the same resolved aliases
3. **Discoverable:** Aliases documented in provider-specific instruction files
4. **Extensible:** New aliases added without code changes
5. **Safe:** Unknown tags rejected before execution
