# Project settings and identity

A project's shared configuration lives in the repository, so every clone and
worktree resolves the same settings with no setup step.

## What to commit

| Path | Commit | Holds |
|---|---|---|
| `.audiagentic/settings.yaml` | yes | project settings (sparse: only keys that differ from the defaults) |
| `.audiagentic/agents/` | yes | project agent definitions, one file per agent |
| `.audiagentic/templates/` | yes | project agent templates |
| everything else under `.audiagentic/` | no | runtime state, logs, caches, generated files |

A `.gitignore` that keeps the tracked files and ignores the rest:

```gitignore
/.audiagentic/*
!/.audiagentic/settings.yaml
!/.audiagentic/agents/
!/.audiagentic/templates/
```

Each worktree reads its own checkout's `.audiagentic/settings.yaml` (never the
main checkout's), so a branch can change project settings like any other file.
Per-person settings belong in the user scope
(`audiagentic config paths` shows where), not in the repository.

## Project identity

The project id names the project in every worktree and clone. It is resolved in
this order:

1. `project.id` in settings (normally the tracked `.audiagentic/settings.yaml`);
2. `project-id` in the legacy `.audiagentic/config/project.yaml`;
3. the repository name of the git `origin` remote;
4. the main checkout's directory name, or this directory's name outside git.

The last step differs between clones, and so does step 3 when remotes point at
differently named repositories. `audiagentic doctor` warns in both cases;
declare the id to fix it:

```yaml
# .audiagentic/settings.yaml
schema_version: 1
project:
  id: my-project
```

Ids use letters, digits, `.`, `_` and `-` (up to 64 characters, starting with a
letter or digit); derived names are normalized to that form. The display name
used by chat providers is separate (`project-name` in the legacy project file,
else the repository name).

See `docs/design/configuration-model.md` on the planning branch for the full
model.
