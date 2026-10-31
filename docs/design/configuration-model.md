# Configuration model

Normative contract for AUDiaGentic configuration, agent definitions and setup.
Plan: `config-setup` (CFG01-CFG10). Converged on 2026-10-28 from three GPT
review rounds and an independent proposal; review record:
`/work/development/tmp/AUDiaGentic/config-review/` on the brutus agent-dev
container (brief, round 1-3 answers, independent proposal).

## Phasing

Approved 2026-10-28: deliver in two phases so the main benefit lands early and
nothing is half-migrated.

**Phase 1 (now)**
- CFG03: resolver with four file scopes only: vendor, user, project (current
  checkout), explicit (`--config` / `AUDIAGENTIC_CONFIG`), then CLI flags.
- CFG04 (part): tracked project settings and identity; no user-project scope.
- CFG05: agent files and templates with single-level `extends`.
- CFG08: `setup` and `doctor`.
- CFG09 (part): migrate only the agent catalog and gateway configuration.

**Phase 2 (when the need is felt)**
- CFG07 qualification evidence store and `qualify` (PR #82's descriptor entry
  covers Linux gpt-auto today).
- user-project and system scopes; provider instances (CFG06 part).
- the rest of CFG09 (providers, model sources, interoperability, logging, rig)
  and CFG10 env-var reduction.

Phase 2 sections of this document stay normative for when they are built;
phase 1 must not contradict them.

## Goals

- One mechanism: one format, one resolver, one precedence order, one merge rule.
- Packaged defaults work with no bootstrap; users write only what they change.
- Worktrees and clones of a repository resolve the same project.
- Errors surface at load time with file, line and key, never at dispatch.
- Configuration is never written by probes or runtime; state and cache live elsewhere.

## Format

- All human-authored configuration is **YAML 1.2**, parsed by one strict loader
  shared by CLI, MCP, gateway and node:
  - YAML 1.2 core scalar resolution only (no YAML 1.1 implicit booleans or octals);
  - duplicate mapping keys, custom tags, object construction, anchors/aliases and
    multiple documents per file are rejected;
  - string keys and JSON-compatible scalar values only;
  - errors report file, line, column, key and schema message.
  Tests must prove these rules; PyYAML `safe_load` defaults do not.
- Every file is validated against **JSON Schema 2020-12**, offline. Foundation
  owns only the envelope (`foundation/contracts/schemas/settings.schema.json`
  in the canonical schema registry: `schema_version`, unknown sections
  rejected). Each top-level section is declared by its owning component as
  `config/components/<component>/settings/<section>.schema.json` (for example
  `project`, `agents`) and composed at load time; a section declared twice is
  an error. Public objects use `additionalProperties: false`. Files may carry a
  `yaml-language-server` `$schema` modeline for editors; optional SchemaStore
  registration.
- Every file has `schema_version: 1`.

Rejected: TOML (no clean multi-line prose for instructions, `tomllib` absent on
Python 3.10), JSON (no comments), mixed formats (two toolchains for one model),
Markdown with frontmatter for agents (frontmatter escapes schema tooling).

## Kinds of data

| Kind | Written by | Location | Layered |
|---|---|---|---|
| Configuration | people | scopes below | yes |
| State | AUDiaGentic | `platformdirs.user_state_dir("audiagentic")`, or a server's configured state root; project runtime in `<checkout>/.audiagentic/state/` (ignored) | no |
| Cache | AUDiaGentic | `platformdirs.user_cache_dir("audiagentic")` | no |
| Runtime | AUDiaGentic | platform runtime dir where available | no |

Provider availability probes, qualification evidence, gateway records and MCP
install operations are state. Nothing in this table's lower three rows may
change a configuration value.

## Scopes and precedence

Lowest to highest. Each file scope has the same shape: `settings.yaml` plus an
optional `agents/` directory (one agent per file).

| # | Scope | Location | Loaded | Tracked |
|---|---|---|---|---|
| 1 | vendor | installed `audiagentic/config/provisioning/foundation/settings.yaml`; packaged agents and templates live with their owning component's config (CFG05) | always | package |
| 2 | system | `/etc/audiagentic/` (Linux), `%PROGRAMDATA%\audiagentic\` (Windows) | only when passed with `--config` | no |
| 3 | user | `platformdirs.user_config_dir("audiagentic")`: `~/.config/audiagentic/`, `%APPDATA%\audiagentic\`, `~/Library/Application Support/audiagentic/` | always | no |
| 4 | project | `<current checkout>/.audiagentic/` | when a project is resolved | yes |
| 5 | user-project | `<user config>/projects/<project-id>.yaml` | when a project is resolved | no |
| 6 | explicit | `--config FILE` or `AUDIAGENTIC_CONFIG` | when given | n/a |
| 7 | CLI flags | command line | when given | n/a |

- The vendor scope is the default. It is never copied; overrides are sparse.
- The project scope is read from the current checkout, never from the git common
  directory: each worktree uses its own branch's settings.
- The user-project scope holds one person's overrides for one project; it applies
  in every worktree and clone with that project identity, and never touches
  tracked files.
- `--config` wins over `AUDIAGENTIC_CONFIG` when both are given.
- Managed security policy (authentication, authorization, TLS, node grants,
  workspace authority) is not part of ordinary precedence: it is applied after
  resolution as an enforced constraint, and a conflicting setting fails rather
  than weakening it. Project mappings alone never authorize node execution.

## Discovery

1. Project root: `--project`, else `AUDIAGENTIC_PROJECT`, else the git top level
   of the working directory (current checkout). No project outside git unless
   given explicitly.
2. Project identity: `project.id` from merged settings, else the git `origin`
   repository name (normalized), else the main checkout directory name. The last
   fallback is provisional: `doctor` reports it and recommends declaring
   `project.id`. Several remotes that normalize to different identities require
   a declared `project.id`. Identity is path-safe (restricted character set,
   never a path or credential-bearing URL) and checked for collisions before it
   names a `projects/<id>.yaml` file. Execution custody is never keyed by
   logical project id alone; each checkout keeps its own workspace identity.
3. Load scopes 1, (2), 3, 4, 5, (6), (7) and merge them in order.
4. Resolve agent templates and provider instances.
5. Validate the final objects and all cross-references (agents -> providers,
   instances, templates; credentials) before any gateway startup or dispatch.

## Merge rule

RFC 7396 JSON Merge Patch, applied scope over scope:

- objects merge recursively; scalars replace;
- arrays replace completely (no append operators);
- `null` removes the key from the lower scope;
- a required value removed by a higher scope fails final validation.

Because `null` means delete, settings are never nullable: an empty or "off"
state is an explicit enum value or object.

Every effective value keeps its origin (scope, file, line), including deletions.
No environment interpolation inside files.

## Settings

```yaml
# ~/.config/audiagentic/settings.yaml
schema_version: 1
agents:
  default: reviewer-gpt-agent
providers:
  gpt-auto:
    enabled: auto            # auto | true | false (policy only; probes never write it)
    cdp: {endpoint: http://127.0.0.1:9222}
    instances:
      default: {project: AUDiaGentic}
      t2: {project: gpt-t2}
gateway:
  mode: automatic
```

```yaml
# <checkout>/.audiagentic/settings.yaml (tracked)
schema_version: 1
project:
  id: audiagentic
agents:
  default: reviewer-gpt-agent
```

```yaml
# ~/.config/audiagentic/projects/audiagentic.yaml (one person, this project)
schema_version: 1
providers:
  gpt-auto:
    instances:
      default: {project: PersonalReview}
```

## Agents and templates

One file per agent in any scope's `agents/`; templates in the vendor (or any
scope's) `templates/` use the same schema. Field names follow the A2A Agent
Card where one exists (`name`, `description`, `skills`), so SH61 projects them
directly.

```yaml
# templates/reviewer.yaml (vendor)
schema_version: 1
id: reviewer
name: Reviewer
description: Reviews plans, designs and changes.
skills: [review]
instructions: |
  Report findings ranked by severity with concrete evidence...
```

```yaml
# agents/reviewer-gpt-agent.yaml (any scope)
schema_version: 1
id: reviewer-gpt-agent
extends: reviewer            # template id; single level only
provider: gpt-auto
instance: default            # optional; defaults to the provider's `default` instance
```

- `extends` names a template; the agent merge-patches over it (RFC 7396). One
  level only; a template cannot extend.
- A higher scope may override a packaged template by id with a sparse file.
- A provider with exactly one session surface needs no `surface`; more than one
  without a declared default is a load-time error.
- Optional agent fields: `model`, `params`, `surface`, `instructions` or
  `instructions_file` (a plain text path relative to the agent file).
- There are no separate prompt, role or execution-profile records.

## Providers

- **Descriptors** (packaged) state capabilities and requirements only.
- **Instances** (settings) are named configurations of one provider; agents
  select one with `instance`. `gpt_auto_t1`/`gpt_auto_t2` were removed in
  favour of instances (CFG06); the key `provider@instance` identifies a target
  wherever state must stay separate per instance.
- **enabled** is policy (`auto` | `true` | `false`, default `auto`).
- **available** is an observation at use time (CLI present, endpoint reachable).
- **qualified** comes from evidence (below).
- A capability executes only when enabled, available and qualified (where the
  surface declares a qualification policy) all hold.

## Qualification evidence

- Vendor evidence ships in the wheel, immutable and versioned.
- Local evidence: `<state>/qualification/v1/<provider>/<surface>/<platform>.yaml`,
  written atomically by `audiagentic qualify [--provider ID] [--surface ID]`.
- A record binds provider, surface, platform, implementation fingerprint,
  package version, qualification spec version, result, time, environment and
  the digest of retained evidence.
- The surface resolver combines vendor and local records and rejects stale or
  incompatible ones. Missing evidence is `unqualified`, never a failure; one
  platform's evidence never stands in for another's.

## Credentials

Credential fields take exactly one typed reference, never a literal secret:

```yaml
gateway:
  authentication:
    token: {file: /run/secrets/audiagentic-token}
providers:
  local-openai:
    credentials:
      api_key: {env: LOCAL_OPENAI_API_KEY}     # or {keychain: service/account}
```

`file:` paths resolve relative to the file that declares them. Secrets resolve
in the process that needs them and are never printed, logged or sent in
requests; `config show` prints the reference.

## Shared gateway server and node

Same settings schema, selected with `--config FILE` (for example
`/etc/audiagentic/settings.yaml`):

```yaml
gateway:
  role: server               # or node
  listen: 0.0.0.0
  port: 8443
  tls:
    certificate: {file: /etc/audiagentic/server.crt}
    private_key: {file: /run/secrets/server-key}
```

## Environment variables

Public: `AUDIAGENTIC_CONFIG` (explicit file, scope 6), `AUDIAGENTIC_PROJECT`
(project root), `AUDIAGENTIC_PROFILE` (component profile: one per process, and
MCP children need a way to receive it), plus the standard `XDG_*` honoured
through `platformdirs`. `AUDIAGENTIC_LOG_LEVEL` remains a documented diagnostic
override, not configuration. New internal variables use the `_AUDIAGENTIC_`
prefix with narrow propagation; replacing `AUDIAGENTIC_REPO_ROOT` must not change
the workspace authority child processes observe. Credential variables named by
`{env: ...}` references are not configuration switches. Internal inter-process
variables stay private and undocumented as configuration; test switches stay
test-scoped. Everything else becomes settings keys
(`tests/unit/architecture/config_inventory.yaml` tracks progress).

## CLI

| Command | Behaviour |
|---|---|
| `audiagentic setup` | Idempotent: creates only needed user config, registers MCP servers in detected harnesses through the CLI entrypoint (no interpreter path, no env), then runs `doctor` |
| `audiagentic doctor` | Read-only checks with exact fixes: config validity, agents, provider enabled/available/qualified, project identity, MCP registration, package data, gateway reachability, permissions |
| `audiagentic config show [KEY] --origin` | Effective values with scope, file and line |
| `audiagentic config validate` | Syntax, schema and cross-references |
| `audiagentic config paths` | Resolved project, config, state and cache paths |
| `audiagentic config edit --scope S` | Open (creating a minimal file if absent) the file for a scope |
| `audiagentic config migrate` | Convert legacy configuration with preview and backup |
| `audiagentic agent list` / `show ID --resolved` / `add ID --extends T --provider P` | Agent management |
| `audiagentic provider list` | Instances with enabled/available/qualified |
| `audiagentic qualify` | Run qualification and write evidence |
| `audiagentic gateway serve --config FILE` / `node serve --config FILE` | Start a configured role |

## Removed or merged

- `~/.audiagentic/config/agents.yaml` prompt/role/execution-profile/agent chain -> agent files and templates.
- `.audiagentic/config/runtime/features/*.yaml` implementation `enabled` flags (and the legacy
  `features.yaml` monolith) -> local observations under `.audiagentic/state/observations/`
  (`enabled:<implementation>`), moved by `audiagentic config migrate`. `providers.<id>.enabled` stays
  the user's own override and wins over the observation; `auto` defers to it, then to availability.
  Component options and feature state remain in the shards until their own migration.
- `AUDIAGENTIC_AUTO_UPDATE_ENABLED`, `STARTUP_STATUS`, `RECONCILE_PROVIDERS_ON_LAUNCH` -> `launch.auto_update`, `launch.status`, `launch.reconcile_providers`; `AUDIAGENTIC_LOCALE` -> `locale`; `AUDIAGENTIC_LOCAL_PROVIDER_BASE_URL` -> the provider's own settings; `AUDIAGENTIC_GATEWAY_PORT` -> internal gateway-to-adapter wiring (`_AUDIAGENTIC_GATEWAY_PORT`), the port itself being `gateway.port`. All done (CFG10 slice 4).
- `foundation/logging.yaml` and `logging.local.yaml`, user and project (done: the `logging` section; `AUDIAGENTIC_LOG_LEVEL` is the one remaining environment override; `silenced` and `redact_patterns` stay additive to the packaged lists).
- `harness/ag.yaml` and `harness/pi.yaml`, user and project (done: the `harness` section, packaged defaults in the vendor settings; `audiagentic config migrate`).
- `model-sources.yaml` (done: `model-sources` section at user and project scope; `audiagentic config migrate`), `provider-policy.yaml` (done: `reconciliation` section, decisions as local state), `providers/<id>.yaml` and
  `runtime/providers.yaml` (done: `providers.<id>`; install and access modes come from the descriptor; `audiagentic config migrate`), `gpt-auto*.yaml` overlays, `interoperability/*.yaml`, `.audiagentic/components/*.yaml` markers -> sections of `settings.yaml`.
- `config/providers/gpt_auto_t1.yaml`, `gpt_auto_t2.yaml` -> `gpt-auto` instances.
- Separate shared gateway `server.yaml` / `node.yaml` schemas -> settings sections.
- `AUDIAGENTIC_HOME`, `AUDIAGENTIC_ROOT`, `AUDIAGENTIC_REPO_ROOT`, `AUDIAGENTIC_COMPONENT_CONFIG_DIRS` and the user-configuration variables -> platform paths, discovery and settings keys.
- The 49 modules that build `.audiagentic` paths themselves -> three owners:
  the configuration resolver (human-authored config), a state-path service
  (ledger, gateway, provider state) and a package-resource resolver
  (`importlib.resources`). Not every path belongs in the config resolver.
- `AUDIAGENTIC_RIG_*` settings -> model-source or provider-instance settings,
  not fifteen loose keys.

Before deleting any file, classify it as configuration, state, cache, generated
artifact or release evidence.

Execution custody, authorization fences, grants and canonical work identity
(SH38 and related) are runtime correctness, not configuration, and stay.

## Mechanisms kept, and why nothing simpler works

| Mechanism | Why |
|---|---|
| Several scopes | Packages, people, teams and operators legitimately own different settings |
| User-project scope | One person must override tracked project settings without editing git |
| Strict schema | Permissive parsing cannot fail early with a location |
| Templates with `extends` | Editable defaults without copying instructions into every agent |
| Provider instances | One transport serves several accounts or remote projects |
| Origin tracking | Without it, layered settings cannot be debugged |
| Separate state | Observations must never change desired configuration |
| Typed credential references | Secrets need their own lifecycle and must never be committed |
| `doctor` | Schemas cannot check binaries, network reachability or permissions |

## Not doing

Generic environment-to-key mapping, template expressions, multi-level
inheritance, conditional includes, drop-in directories, list append operators,
automatic loading of system scope, remote configuration download, a second
provider or capability registry.

## Plan mapping

| Item | Change |
|---|---|
| CFG01 | This document |
| CFG02 | Inventory and guard test (PR #83) |
| CFG03 | Resolver: strict YAML, JSON Schema, RFC 7396, provenance, `platformdirs`; `config show/validate/paths` |
| CFG04 | Tracked project config, identity, worktree discovery, user-project overrides |
| CFG05 | Agent files, templates, `extends`, early reference validation |
| CFG06 | enabled/available/qualified; provider instances (retires gpt_auto_t1/t2) |
| CFG07 | Qualification evidence, `qualify`, surface resolution from evidence |
| CFG08 | `setup`, `doctor`, portable MCP registration, installed-wheel qualification |
| CFG09 | Migrate agent catalog, providers, model sources (PC12), shared server/node, project and remaining subsystems; `config migrate` |
| CFG10 | Public env vars down to three; no unmanaged path builders |
| SH42 | Owns installed release qualification and deployment docs; absorbs SH57 and SH59 |
| SH53 | Uses CFG07's evidence schema and producer |
| PC10 | Delivered through CFG06 |
| DI01 | Checked in CFG06 and CFG08 |
| MP02 | Packaging and MCP registration aligned with CFG08 |
| SH38-SH41, SH60-SH62 | Execution and interoperability contracts unchanged; adopt the resolver in CFG09 |

Detailed per-item mapping (from the alternative round-2 answer):

| Plan | Disposition |
|---|---|
| SH35, SH37 | Amend: unified deployment settings; migrate standalone configuration |
| SH36, SH40, SH44, SH49-SH52, SH54-SH56, SH58, SH60 | Preserve |
| SH38 | Amend: unified loader, same ownership and custody semantics |
| SH39, SH45-SH48 | Amend: separate capability, instance and qualification resolution |
| SH41, SH53 | Amend: one evidence representation (CFG07), not another registry |
| SH42 | Consolidate: documentation and release qualification; absorbs SH57, SH59 |
| SH61, SH62 | Amend lightly: project Agent Card / ACP capabilities from resolved agents |
| PC09, PC11 | Amend: descriptors separate from instances; provider vs instance catalog operations |
| PC10 | Replace activation mechanism (CFG06) |
| PC12 | Amend: model sources in settings (CFG09) |
| PC13, PC14 | Preserve |
| DI01 | Largely subsumed: no generated disabled-provider footprint |
| MP02 | Amend: wheel resources and installed MCP entrypoints (CFG08) |

## Migration (one transition release)

1. Read legacy configuration only when new configuration is absent; reject
   ambiguous mixed sources instead of picking one.
2. `config migrate --dry-run` reports changes without writing.
3. Generate minimal YAML (no copied defaults), validate before writing, back up
   originals, report unmapped fields.
4. Never write plaintext secrets; shared-service changes need authorization.
5. Preserve live state, journals, grants and custody records.
6. Remove legacy readers after the transition; never leave the old readers
   independently authoritative alongside the resolver.

Sequencing: CFG07 before CFG08's installed qualification; CFG09 keeps legacy
readers until migration and rollback tests pass; CFG10 only after every
supported entrypoint uses the resolver.

## Review record and resolved conflicts

Two GPT round-2 answers exist: the one captured through the gateway and a more
thorough one recovered from the orphaned request (GA27). Where they conflict
with round 3, this document keeps:

- **Per-person overrides in `<user-config>/projects/<id>.yaml`, not a
  checkout-local `.audiagentic/local/`.** A checkout-local file must be recreated
  in every worktree, the pain this redesign removes; the common case (one
  person's settings for one repository) applies across worktrees.
- **System scope only through `--config`**, so desktops have no hidden dependency
  on `/etc`.
- **Instances nested under `providers.<id>.instances`**, agents naming `provider`
  and an optional `instance`.
- **A separate `templates/` namespace** instead of `template: true` agents, so a
  template can never run as an agent.
- **The AST inventory (PR #83)** over text-match counts: `AUDIAGENTIC_MARKERS` is a
  Python constant, and the worker-activity variables are set by the worker host
  for its children (internal).

## Code ownership (phase 1)

Mechanics live in foundation, extending existing modules rather than adding
parallel ones: `foundation/config/strict_yaml.py` (strict loader),
`foundation/config/merge.py` (`merge_patch` next to the legacy `deep_merge`),
`foundation/config/settings.py` (scopes, discovery, validation, provenance),
`foundation/paths/home.py` (platformdirs user config/state/cache dirs) and
`foundation/paths/project.py` (`discover_checkout_root` next to the legacy
`find_project_root`). Domain keys are owned by components through their
section schemas. The CLI adapter (`commands/settings.py`) only translates
arguments and output.
