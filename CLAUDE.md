<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

# CLAUDE.md

This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.

## Canonical rule

- Do not reinterpret `@ag-plan`, `@ag-implement`, `@ag-review`, `@ag-audit`, `@ag-check-in-prep`.
- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate
  workflow semantics layer.
- Keep provenance visible: provider id, surface, and session id should survive normalization.

## Bridge

When a Claude prompt begins with a canonical tag, use the shared prompt-trigger bridge:

```powershell
python tools/claude_prompt_trigger_bridge.py --project-root .
```

If a hook surface is available, `UserPromptSubmit` should hand the raw prompt to the bridge
before planning starts. If the hook surface is partial, fall back to the bridge and keep the
shared launch grammar unchanged.

## Tag shortcuts and aliases

Tag and provider aliases are centralized in `.audiagentic/prompt-syntax.yaml` and work in all surfaces:

Canonical tags:

- ag-plan
- ag-implement
- ag-review
- ag-audit
- ag-check-in-prep

- `agp` -> `ag-plan`
- `agi` -> `ag-implement`
- `agr` -> `ag-review`
- `aga` -> `ag-audit`
- `agc` -> `ag-check-in-prep`

- `cx` -> `codex`
- `cld` -> `claude`
- `cln` -> `cline`
- `gm` -> `gemini`
- `opc` -> `opencode`
- `cp` -> `copilot`

All of these are equivalent:

```text
@ag-review provider=cline
@agr provider=cline
@review provider=cline
@r provider=cline
@ag-review-cline
@r-cline
```

## Planning item creation policy

**Planning items (requests, specs, plans, tasks) can only be created with explicit user approval.**

- Do not autonomously create planning items during analysis, review, or exploration work
- If analysis suggests a new request or spec is needed, report findings and ask for approval
- Use the canonical tags (`@ag-plan`) to signal planning work that requires user direction
- Only create planning items in response to explicit user instruction or approved workflow prompts

This prevents unintended expansion of the planning record and maintains user control over scope.

## Review doctrine

- review prompts should stay read-focused unless the normalized request explicitly allows more
- do not broaden review into implementation work
- keep tracked docs and release artifacts synchronized with the job record
