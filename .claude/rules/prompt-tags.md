<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

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
