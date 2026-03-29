# Project Layout and Local State

## Tracked project layout

```text
docs/
  specifications/
    architecture/
    decisions/
  implementation/
    providers/
  releases/
.audiagentic/
  project.yaml
  components.yaml
  providers.yaml
  runtime/
```

## Runtime structure

```text
.audiagentic/runtime/
  approvals/
  jobs/
  ledger/
    fragments/
    sync/
    temp/
  logs/
  overlay/discord/
  temp/
  worktrees/
```

## Ownership rules

- tracked docs are written only by deterministic scripts or explicit lifecycle modules
- jobs must not write arbitrary tracked docs directly
- jobs may write runtime fragments and runtime artifacts
- tracked release docs are updated only by release/ledger scripts listed in the file ownership matrix

## Git ignore recommendation

```gitignore
.audiagentic/runtime/
```
