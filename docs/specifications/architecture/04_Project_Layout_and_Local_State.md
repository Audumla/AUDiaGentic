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
  providers.yaml  # access-mode, model catalog, prompt-surface, and install policy settings
  prompt-syntax.yaml
  prompts/
  runtime/
AGENTS.md
CLAUDE.md
GEMINI.md
.clinerules/
.claude/
.agents/skills/
```

## Runtime structure

```text
.audiagentic/runtime/
  approvals/
  jobs/
    launches/
    reviews/
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

Do not ignore the entire `.audiagentic/` tree. The tracked install baseline lives partly under
`.audiagentic/`, while only `.audiagentic/runtime/` is runtime-only.


## Phase 3.2 runtime additions

Prompt launch requests, review reports, and review bundles are runtime-only artifacts. They must live under `.audiagentic/runtime/jobs/` or a child path such as `.audiagentic/runtime/jobs/<job-id>/reviews/` and must not be written directly into tracked docs.

## Installable baseline reminder

The tracked files under `.audiagentic/`, the managed prompt templates, and the managed
provider instruction surfaces together define the installable AUDiaGentic project baseline.
They are not runtime output and must remain visible to Git so they can be applied to other
projects.
