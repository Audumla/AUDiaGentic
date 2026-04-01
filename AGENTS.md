# AGENTS.md

This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.

## Canonical rule

- Do not reinterpret `@plan`, `@implement`, `@review`, `@audit`, or `@check-in-prep`.
- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate
  workflow semantics layer.
- Keep provenance visible: provider id, surface, and session id should survive normalization.

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
  - `@plan`
  - `@implement`
  - `@review`
  - `@audit`
  - `@check-in-prep`
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
@review provider=codex id=job_001 ctx=documentation t=review-default
Review the current project state and call out any gaps.
```

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

## Skills

Each canonical action maps to a focused skill under `.agents/skills/`:

- plan
- implement
- review
- audit
- check-in-prep

## Review doctrine

- review prompts should stay read-focused unless the normalized request explicitly allows more
- do not broaden review into implementation work
- keep tracked docs and release artifacts synchronized with the job record
