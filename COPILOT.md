<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

# COPILOT.md

This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.

## Canonical rule

- Do not reinterpret `@ag-plan`, `@ag-implement`, `@ag-review`, `@ag-audit`, or `@ag-check-in-prep`.
- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate
  workflow semantics layer.
- Keep provenance visible: provider id, surface, and session id should survive normalization.

## Bridge

Use the shared prompt-trigger bridge for Copilot:

```powershell
python tools/copilot_prompt_trigger_bridge.py --project-root .
```

If a native hook path is present in the active Copilot build, it should normalize into the same
shared launch contract. If it is not stable, the bridge stays authoritative.

## Review doctrine

- review prompts should stay read-focused unless the normalized request explicitly allows more
- do not broaden review into implementation work
- keep tracked docs and release artifacts synchronized with the job record
