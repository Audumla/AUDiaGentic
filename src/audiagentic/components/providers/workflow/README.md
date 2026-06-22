# components/providers/workflow/

Workflow helpers specific to provider maintenance.

## Intent

Hold command-style workflows that act on providers as managed dependencies instead of as job execution targets.

## Current Scope

- `provider_cli.py` drives install, uninstall, and repair actions for provider CLIs using descriptor-owned recipes.

Keep provider runtime execution in adapters/services. Keep host dependency workflows here.
