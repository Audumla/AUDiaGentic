# $display_name

This repository uses AUDiaGentic workflow jobs.

## Bridge

When a prompt begins with a workflow tag, route it through the repo-owned bridge:

```powershell
$bridge_command
```

If a native hook path is present in the active Gemini build, it should normalize into the
same shared launch contract. If it is not stable, the bridge stays authoritative.

## Prompt tag doctrine

- Parse only the first non-empty line for the workflow tag.
- Keep tag semantics identical to the shared AUDiaGentic launch contract.
- Do not invent provider-specific alternate tags.
- Preserve raw prompt text in provenance metadata.
- Keep provenance visible: provider id, surface, and session id should survive normalization.
