# $display_name

This repository uses AUDiaGentic workflow jobs.

## Bridge

When a prompt begins with a workflow tag, route it through the repo-owned bridge:

```powershell
$bridge_command
```

If a hook or instruction surface is partial, fall back to the bridge and keep the shared
launch grammar unchanged.

## Prompt tag doctrine

- Parse only the first non-empty line for the workflow tag.
- Keep tag semantics identical to the shared AUDiaGentic launch contract.
- Do not invent provider-specific alternate tags.
- Preserve raw prompt text in provenance metadata.
- Keep provenance visible: provider id, surface, and session id should survive normalization.
