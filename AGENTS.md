# AGENTS.md

This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.

## Canonical rule

- Do not reinterpret `@plan`, `@implement`, `@review`, `@audit`, or `@check-in-prep`.
- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate
  workflow semantics layer.
- Keep provenance visible: provider id, surface, and session id should survive normalization.

## Codex path

Codex should use the shared prompt-trigger bridge:

```powershell
python tools/codex_prompt_trigger_bridge.py --project-root .
```

If a hook or instruction surface is partial, fall back to the bridge and keep the shared launch
grammar unchanged.

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

