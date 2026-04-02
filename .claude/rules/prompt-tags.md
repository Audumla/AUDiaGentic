# Prompt tag doctrine

Canonical tags:

- `@ag-plan`
- `@ag-implement`
- `@ag-review`
- `@ag-audit`
- `@ag-check-in-prep`

Rules:

- parse only the first non-empty line for the canonical tag
- keep tag semantics identical to the shared AUDiaGentic launch contract
- do not invent provider-specific alternate tags
- preserve raw prompt text in provenance metadata
- route tagged prompts through the shared bridge when a native hook path is not stable
- canonical names are config-managed in `.audiagentic/prompt-syntax.yaml`; run
  `python tools/regenerate_tag_surfaces.py --project-root .` after renaming tags or aliases

## Tag aliases and shortcuts

Centralized in `.audiagentic/prompt-syntax.yaml`. All of these are equivalent:

- `agp` -> `ag-plan`
- `agi` -> `ag-implement`
- `agr` -> `ag-review`
- `aga` -> `ag-audit`
- `agc` -> `ag-check-in-prep`

- `cx` -> `codex`
- `cld` -> `claude`
- `cln` -> `cline`
- `gm` -> `gemini`
- `cp` -> `copilot`

Use shortcuts for brevity:

```text
@agr-cln target=packet:PKT-PRV-033
Review the implementation status.
```
