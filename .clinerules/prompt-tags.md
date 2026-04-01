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

## Tag aliases and shortcuts

Centralized in `.audiagentic/prompt-syntax.yaml`. All of these are equivalent:

- `@r` = `@review` (tag alias)
- `@review provider=cln` = `@review provider=cline` (provider alias)
- `@r-cln` = `@review provider=cline` (combined shortcut)
- `@review-cline` = `@review provider=cline` (suffix form)

Use shortcuts for brevity:

```text
@r-cln target=packet:PKT-PRV-033
Review the implementation status.
```

