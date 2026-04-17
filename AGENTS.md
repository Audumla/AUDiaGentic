<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

# AGENTS.md

This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.

## Canonical rule

- Do not reinterpret `@ag-plan`, `@ag-implement`, `@ag-review`, `@ag-audit`, `@ag-check-in-prep`.
- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate
  workflow semantics layer.
- Keep provenance visible: provider id, surface, and session id should survive normalization.
- Canonical names are config-managed in `.audiagentic/prompt-syntax.yaml`; run
  `python tools/regenerate_tag_surfaces.py --project-root .` after renaming tags or aliases.

## Prompt-calling protocol

If a prompt begins with a canonical tag, treat it as a workflow launch request, not ordinary
chat.

## Bridge mechanics

The bridge is the execution boundary for tagged prompts.

- Read the raw tagged prompt, including the first non-empty line and the prompt body.
- Normalize the tag, provider shorthand, and argument aliases using
  `.audiagentic/prompt-syntax.yaml`.
- Preserve provenance fields through normalization: provider id, surface, and session id.
- Apply project defaults when the prompt omits `id`, `context`, `output`, or `template`.
- Treat the canonical action tags as workflow selectors, not as free-form instructions:
- `@ag-plan`
- `@ag-implement`
- `@ag-review`
- `@ag-audit`
- `@ag-check-in-prep`
- Treat provider shorthands as provider selectors that still route through the same normalized
  launch contract.
- If the prompt is tagged but no explicit subject is supplied, let the bridge create the default
  generic subject/job identity rather than inventing ad hoc semantics.
- Stream or capture provider output through AUDiaGentic-owned runtime artifacts; the provider
  should not own persistence policy.

The Codex launch path is:

```powershell
python tools/codex_prompt_trigger_bridge.py --project-root .
```

The shared bridge normalizes the raw prompt and forwards it into `prompt-launch`, so the
tagged prompt becomes a job request with preserved provenance and project defaults.

## Codex path

Codex should use the shared prompt-trigger bridge:

```powershell
python tools/codex_prompt_trigger_bridge.py --project-root .
```

If a hook or instruction surface is partial, fall back to the bridge and keep the shared launch
grammar unchanged.

## Standard prompt shape

Prefer the short, defaults-first form:

```text
@ag-review provider=codex id=job_001 ctx=documentation t=review-default
Review the current project state and call out any gaps.
```

When a provider/tag default template exists under `.audiagentic/prompts/<tag>/`, the shortest
form is also valid:

```text
@ag-review
```

In that case the bridge should:
- resolve the provider from the suffix
- load the provider or shared default template
- create the default job/subject identity if none is supplied
- preserve provenance through normalization

The bridge should accept the long-form canonical names as well:

- `provider`
- `id`
- `context`
- `output`
- `template`

and the common aliases:

- `ctx` -> `context`
- `out` -> `output`
- `t` -> `template`

## Tag and provider aliases

Centralized in `.audiagentic/prompt-syntax.yaml`. Available shortcuts:

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

## Skills

- `ag-plan`
- `ag-implement`
- `ag-review`
- `ag-audit`
- `ag-check-in-prep`

## MCP Tool Usage

- **Planning activities** (requests, specs, tasks, plans, standards, workpackages) must use the `audiagentic-planning` MCP server for all planning item operations (tm_list, tm_create, tm_edit, tm_get, tm_delete, tm_standards, tm_docs, tm_relink, tm_claim, tm_move, tm_package, tm_section)
- **Context searching** (project documentation) must use the `audiagentic-knowledge` MCP server for knowledge operations (search_pages, knowledge_get_page, scaffold_page, scan_drift, doctor, validate, status)
- These MCPs provide the execution layer for planning work - agents should not implement these capabilities directly

## Review doctrine

- review prompts should stay read-focused unless the normalized request explicitly allows more
- do not broaden review into implementation work
- keep tracked docs and release artifacts synchronized with the job record
