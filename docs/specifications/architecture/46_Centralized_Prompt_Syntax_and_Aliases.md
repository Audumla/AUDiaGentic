# Centralized Prompt Syntax and Aliases

**Status:** VERIFIED  
**Applies to:** All providers (Claude, Cline, Codex, Gemini, Copilot, Continue, local-openai, Qwen)

---

## Overview

Prompt tag syntax and aliases are centralized in `.audiagentic/prompt-syntax.yaml` and shared across all provider implementations.

Canonical workflow tags use the `ag-*` form:

- `ag-plan`
- `ag-implement`
- `ag-review`
- `ag-audit`
- `ag-check-in-prep`

Those names are config-managed so the same tag vocabulary can be rendered consistently across:

- CLI and editor surfaces
- provider bridges
- skill surfaces
- instruction docs

Whenever aliases or canonical names change, regenerate the derived surfaces with:

```powershell
python tools/regenerate_tag_surfaces.py --project-root .
```

---

## Configuration File

**Location:** `.audiagentic/prompt-syntax.yaml`

### Tag Aliases

Map shorthand tags to canonical actions:

```yaml
tag-aliases:
  agp: ag-plan
  agi: ag-implement
  agr: ag-review
  aga: ag-audit
  agc: ag-check-in-prep
  p: ag-plan
  i: ag-implement
  r: ag-review
  a: ag-audit
  c: ag-check-in-prep
```

Usage: `@agp` expands to `@ag-plan`

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

Usage: `@ag-plan provider=cln` expands to `@ag-plan provider=cline`

### Combined Aliases

Direct tag+provider combinations for convenience:

```yaml
combined-aliases:
  agr-cln: ag-review provider=cline
  agi-cld: ag-implement provider=claude
  agp-cx: ag-plan provider=codex
```

Usage: `@agr-cln` directly expands to `@ag-review provider=cline`

---

## Syntax Examples

All of these are equivalent and resolve to the same request:

```text
@ag-review provider=cline
@agr provider=cline
@ag-review-cline
@agr-cln
```

---

## How Aliases Work

1. **Prompt Parser** (`src/audiagentic/execution/jobs/prompt_parser.py`)
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

### Step 2: Re-generate derived surfaces

Run the shared regeneration tool so instruction surfaces and skill files stay in sync:

```powershell
python tools/regenerate_tag_surfaces.py --project-root .
```

### Step 3: No provider-specific changes needed

All providers automatically recognize new aliases through the shared parser and bridge.

---

## Validation

**Contract:** `.audiagentic/prompt-syntax.yaml` conforms to `src/audiagentic/contracts/schemas/prompt-syntax.schema.json`

**Validation happens at:**
- Bridge startup (when loading syntax)
- Prompt parser initialization
- JSON schema validation in CI/CD

---

## Related Files

- `src/audiagentic/execution/jobs/prompt_parser.py` — Tag resolution logic
- `src/audiagentic/execution/jobs/prompt_syntax.py` — Config loading
- `src/audiagentic/contracts/schemas/prompt-syntax.schema.json` — Schema definition
- `tools/regenerate_tag_surfaces.py` — Derived instruction surface regeneration
- `tools/claude_hooks.py` — Hook-based tag detection
- `tools/claude_prompt_trigger_bridge.py` — Claude bridge
- `CLAUDE.md` — Claude-specific instructions

---

## Principles

1. **Centralized:** Single source of truth in `.audiagentic/prompt-syntax.yaml`
2. **Consistent:** All providers use the same resolved aliases
3. **Discoverable:** Aliases are documented in provider-specific instruction files
4. **Extensible:** New aliases added without code changes
5. **Safe:** Unknown tags rejected before execution
