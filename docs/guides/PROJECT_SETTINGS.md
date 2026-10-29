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
letter or digit); derived names are normalized to that form. Providers such as
gpt-auto use the project name to find their project (for gpt-auto, the ChatGPT
project of that name): an explicit `project-name` in the legacy project file
wins, then `project.id`, then the repository name. A repository with no remote
and no `project.id` is named after its directory, which differs between clones.

See `docs/design/configuration-model.md` on the planning branch for the full
model.

## Provider and gateway settings

Both sections are validated like the rest of `settings.yaml`; `audiagentic config
show --origin` reports which file set each value and `audiagentic config validate`
checks every scope. Edits apply on the next read, without restarting a process.
Gateway and provider policy is normally per machine, so set it in the user
settings (`audiagentic config paths`), not in the repository.

### `providers.<id>.enabled`

```yaml
providers:
  gpt-auto:
    enabled: auto   # auto (default) | true | false
```

`true` and `false` decide outright. Under `auto` a provider is used when it is
observed to be available (its CLI is found, or its browser answers), so a clean
install needs no enablement step. A failed check never disables a provider or
removes its generated configuration; only `enabled: false` (or
`set_provider_enabled`) does. `audiagentic doctor` reports availability.

### `gateway`

| Key | Meaning | Legacy variable |
|---|---|---|
| `implementation` | `automatic` (default: every session attaches to one shared gateway), `standalone`, or `embedded` (deprecated: an in-process gateway per caller) | `AUDIAGENTIC_GATEWAY_MODE` |
| `port` | loopback port of the automatic gateway | `AUDIAGENTIC_GATEWAY_PORT` |
| `idle_grace_seconds` | idle time before an automatic gateway exits; 0 keeps it warm | `AUDIAGENTIC_GATEWAY_IDLE_GRACE_SECONDS` |
| `queue_backend` | work-queue backend (`in-memory`) | `AUDIAGENTIC_GATEWAY_QUEUE_BACKEND` |
| `restart_wait_seconds` | how long a restart waits for the old gateway | `AUDIAGENTIC_GATEWAY_RESTART_WAIT_SECONDS` |
| `embedded_with_live_shared_owner` | `refuse` (default) or `warn` | `AUDIAGENTIC_GATEWAY_EMBEDDED_ALLOW` |
| `console_trace.mode` / `.file` / `.max_chars` | operator trace detail, file and line length | `AUDIAGENTIC_GATEWAY_CONSOLE_TRACE*` |
| `dashboard.recent_seconds` | window of recent requests the dashboard shows | `AUDIAGENTIC_GATEWAY_DASHBOARD_RECENT_SECONDS` |
| `retention`, `watchdog` | machine retention and watchdog policy | `AUDIAGENTIC_GATEWAY_RETENTION_POLICY`, `..._WATCHDOG_POLICY` (JSON file) |

Transition: for one release the legacy variable still overrides its setting,
and a legacy `~/.audiagentic/gateway-retention.json` or `gateway-watchdog.json`
is read only when the matching section is absent. If both exist the policy is
treated as invalid (purges and deletions stay off) and a warning names the
conflict; remove one. The shared server/node configuration is not part of these
settings yet.
