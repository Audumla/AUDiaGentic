# Copilot instructions

This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.

## Canonical rule

- Do not reinterpret `@plan`, `@implement`, `@review`, `@audit`, or `@check-in-prep`.
- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate
  workflow semantics layer.
- Keep provenance visible: provider id, surface, and session id should survive normalization.

## Bridge

Use the shared prompt-trigger bridge for Copilot surfaces:

```powershell
python tools/copilot_prompt_trigger_bridge.py --project-root .
```

If a surface cannot be routed through the wrapper, exact canonical tag support is not
guaranteed.

