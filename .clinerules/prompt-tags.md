<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

# Prompt tag doctrine

Rules:

- Parse only the first non-empty line for the workflow tag.
- Keep tag semantics identical to the shared AUDiaGentic launch contract.
- Do not invent provider-specific alternate tags.
- Preserve raw prompt text in provenance metadata.
- Route tagged prompts through the shared bridge when a native hook path is not stable.
- Canonical names are config-managed in `.audiagentic/config/execution/prompt-syntax.yaml`;
  run `python tools/regenerate_tag_surfaces.py --project-root .` after renaming tags or aliases.
