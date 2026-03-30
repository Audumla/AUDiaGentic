# Prompt tag doctrine

Canonical tags:

- `@plan`
- `@implement`
- `@review`
- `@audit`
- `@check-in-prep`

Rules:

- parse only the first non-empty line for the canonical tag
- keep tag semantics identical to the shared AUDiaGentic launch contract
- do not invent provider-specific alternate tags
- preserve raw prompt text in provenance metadata
- route tagged prompts through the shared bridge when a native hook path is not stable

