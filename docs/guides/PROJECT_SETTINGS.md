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
2. the repository name of the git `origin` remote;
3. the main checkout's directory name, or this directory's name outside git.

The last step differs between clones, and so does step 2 when remotes point at
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

### `home`

```yaml
# user settings (audiagentic config paths shows where)
schema_version: 1
home: /srv/audiagentic/home
```

The AUDiaGentic home holds the shared gateway's service records and token, provider
runtime state, harness configuration and the legacy agent catalog. Every process on a
machine must use the same one: two homes mean two gateway services fighting over one
port, and agents defined in one invisible from the other. A harness that starts MCP
servers without your environment (a user-scope registration from `setup harness`) sees
no `_AUDIAGENTIC_HOME`, so choose the home here and they all agree.

Precedence: the `_AUDIAGENTIC_HOME` environment variable (it wins, and a service passes it
to its children), then this setting, then `~/.audiagentic`. Like the gateway section it is
read from the machine scopes only, so a project's own `settings.yaml` cannot move it. An
invalid settings file stops the command with its file, line and key instead of quietly
using a different home. `audiagentic config paths` prints the home in effect and which of
the three chose it.

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

### `providers.<id>.instances`

```yaml
providers:
  gpt-auto:
    instances:
      first:
        project-url: https://example.test/projects/first
      second:
        project-url: https://example.test/projects/second
```

An instance is a named set of options for one provider, merged over that
provider's own options (RFC 7396, so a `null` removes a key). An agent selects it
with `instance: first` next to its `provider`; the provider's own validation
checks the options. Sessions, queues and evidence are kept apart per instance
(`gpt-auto@first`), while the provider's descriptor, adapter, `enabled` policy
and availability are shared. Names are lowercase letters, digits, `-` and `_`
(up to 32). An unknown name is an error that lists the configured ones. The
provider's own option file stays the base layer until its settings migrate.

## Changing settings from the command line

```
audiagentic config set providers.pi.enabled=false agents.default=reviewer
audiagentic config set --unset providers.pi.enabled
audiagentic config set --scope user home=/srv/audiagentic --dry-run
```

`config set` edits one settings file: the project's `.audiagentic/settings.yaml`
by default, or the user file with `--scope user`. It never picks a scope for you
and never touches the vendor defaults. Values are YAML scalars (`false`, `7`,
`reviewer`) or JSON for text, lists and objects (`'"123"'`, `'[1, 2]'`); a dot in
a key part is written `\.`. `--unset KEY` (or a `null` value) removes a key.

- Comments, blank lines and key order in the file are kept; only the lines for
  the changed keys move. A file the editor cannot change without altering other
  content is refused untouched.
- The result must pass the same strict validation the resolver applies, and a
  section that is only read from the machine scopes (`gateway`, `home`) is
  refused in the project file.
- If the file changes while the command runs (an editor save, another writer),
  nothing is written and the command asks you to run it again. Concurrent
  commands are serialized.
- The previous content is kept as one of the last five backups under the user
  state directory (`config paths` shows it). Symbolic-linked settings files or
  directories are refused. `--dry-run` shows the diff only.
- The output says when a higher scope overrides what was just written.

### `gateway`

The gateway is shared by every project and session on the machine, so this
section is read from the machine scopes only (the user settings, or a file passed
with `--config` / `AUDIAGENTIC_CONFIG`). A `gateway:` block in a project's own
`.audiagentic/settings.yaml` is valid but has no effect.

| Key | Meaning |
|---|---|
| `implementation` | `automatic` (default: every session attaches to one shared gateway), `standalone`, or `embedded` (deprecated: an in-process gateway per caller) |
| `port` | loopback port of the automatic gateway |
| `idle_grace_seconds` | idle time before an automatic gateway exits; 0 keeps it warm |
| `queue_backend` | work-queue backend; only `in-memory` exists, anything else fails closed |
| `restart_wait_seconds` | how long a restart waits for the old gateway |
| `console_trace.mode` / `.file` / `.max_chars` | operator trace detail, file and line length |
| `dashboard.recent_seconds` | window of recent requests the dashboard shows |
| `retention` | machine retention policy: purge, age, batch size, history limit, per-journal byte caps, journal days |
| `watchdog` | execution watchdog lease, ceiling and grace periods |

A settings file that stops validating does not take a running gateway down. Values
read once to decide something (`port`, `implementation`, `queue_backend`,
`restart_wait_seconds`) fail with the file, line and key. Values a running service
reads continually (`console_trace.*`, `idle_grace_seconds`, `dashboard.recent_seconds`)
keep their last valid value, the problem is logged once, and the next valid edit
applies without a restart.

`retention` and `watchdog` are validated as a whole: an invalid policy is
reported in the log and treated as unavailable, which keeps purges and deletions
off. Whether an embedded gateway may run beside a live shared one is the
`allow-with-live-shared-owner` option of the `embedded` implementation, not a
setting. The shared server and node configuration is not part of these settings
yet.
