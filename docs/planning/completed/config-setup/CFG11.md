---
id: CFG11
order: 0
plan: config-setup
state: completed
created-at: '2026-10-31T03:41:56.742276+00:00'
breadth: ''
skill: advanced
created-by: agent
work: L
priority: P1
---

# CFG09 phase 2: migrate the remaining readers and path-builders, config migrate

## Description

CFG09 was completed for phase 1 only (agent catalog, gateway settings). This item carries the phase 2 remainder so it has an active owner: the ~46 modules in tests/unit/architecture/config_inventory.yaml path-builders that join .audiagentic paths themselves, the remaining legacy readers (model sources PC12, provider option files, interoperability, component markers, logging; the shared-gateway server/node/connector documents are a decided exception, see Notes), `audiagentic config migrate` with backup and rollback, and user-project scope. The provider feature-state shard (providers.yaml: enabled, options, per-feature state) and the per-provider option files are one migration with one contract. Legacy readers stay only until migration and rollback tests pass; no compatibility paths without an approved obligation.

## Steps

1. Inventory the provider shard (enabled, options, per-feature state) and every consumer across providers, coding_lsp, memory, planning and gateway; define destination settings keys, precedence, migration, rollback and removal criteria; GPT review.
2. Migrate providers (shard and option files) onto settings with config migrate.
3. Migrate model sources, interoperability, component markers and logging, one subsystem per PR, deleting the old reader in the same PR. (Shared server/node/connector documents: deferred, see Notes.)
4. Drive the path-builders list in config_inventory.yaml to empty.
5. User-project scope and scope isolation/conflict tests.

## Detailed Solution & Technical Design

### Provider shard and feature-state design (step 1)

Status: revised after GPT review `req_wt-planning_f8c511996c70` (ADJUST; all seven findings accepted).

Decision basis: docs/design/configuration-model.md "Removed or merged" sends
`.audiagentic/config/runtime/features/*.yaml` to "`providers.<id>.enabled` policy plus state
observations" and says not every path belongs in the resolver.

**Inventory first.** Before any code, list every persisted field in the shards, with its kind
(intent, derived, observation) and consumer. The shard holds: component-level `features.<kind:id>`
and `implementations.<id>.{enabled,options,features.<kind:id>}`; three states per feature enable
(absent, explicit false, explicit true; see `get_implementation_feature_enabled_explicit`); legacy
nested feature maps. Unknown legacy fields are reported by migrate, never silently dropped.

**Consumers** (all through `foundation/features/state.py`): providers (`provider_config`,
`feature_resolution`, `lifecycle`, `project_purge`, onboarding), coding_lsp, memory, planning,
gateway.

**API shape (not "re-back unchanged").** Two separate surfaces replace the dict-replacing setters:
- intent: scope-aware, sparse, validated operations (`set_intent(scope, path, value)` /
  `clear_intent`) that write settings through `write_settings_patch`, plus read-only effective
  resolution that returns a tri-state (absent/false/true) with provenance;
- observations: a state-path service API used by reconcile, qualification and probes.
Reconcile may call only the observation API and never an intent setter. Compatibility wrappers over
the old function names live only inside the atomic cutover PR and are deleted in it.

**Settings schema.** One foundation-owned `features` section:
`features.<component>.{features.<kind:id>, implementations.<id>.{enabled,options,features.<kind:id>}}`,
validated against descriptor `options_schema`, descriptor defaults below vendor scope.

**Provider enablement truth table** (single rule, no arbitrary precedence).
The shards are gitignored per-host files, so a provider's persisted `enabled` is lifecycle state
(what enable/disable/reconcile applied on this host), not policy. It becomes the local observation
`providers` / `<id>.enabled`. `providers.<id>.enabled` in settings stays the user's own override:
`false` always disables; `true` permits activation (still subject to the host being available);
`auto` (default) defers to the local observation, else to availability. Reconcile and the lifecycle
commands write only the observation, never the policy; migrate never writes the policy, and reports
a conflicting existing value instead of merging over it. Per-feature `enabled` (explicit false
disables a capability) and options are user intent and move to the `features` settings section.

**Observations** (availability, qualification, last reconcile, surface/catalog outcomes) go to the
state-path service, never to settings. Contract per key: owner component, scope (project or user),
timestamp, staleness rule (re-probe on launch or after a stated TTL), atomic update. Execution
custody, authorization fences and grants (SH38) stay out of scope.

**Concurrency.** Writes take a cross-process lock around read/merge/validate/write, patch only the
targeted keys and invalidate `resolve_settings_cached`. Tests: concurrent enable/disable vs
reconcile vs migrate vs rollback, and cache invalidation.

**Migration and rollback (transactional).** `audiagentic config migrate` is dry-run by default.
It builds a versioned manifest: source file hashes, destination scope, original key presence and
values, applied values. Backups are staged and verified before any mutation; the patch is applied
under the lock; sources are then renamed to `<name>.migrated` (an existing `.migrated` is never
overwritten; a numbered suffix is used). An interrupted run is recoverable from the manifest.
Mixed nested/flat keys are normalised first. Conflicting existing settings are refused, not
merged. `--rollback` compares-and-swaps each applied key (restores only values still equal to the
applied value, so later user edits survive) and restores sources from the verified backups.

**PR order (single authority at every merge point).**
(a) infrastructure, no authority change: `features` schema, state-path service, lock, intent and
observation APIs, migration manifest library, with tests.
(b) the provider cutover, one atomic PR: migrate and rollback for providers (shard, option files,
policy, instances), every provider reader and writer, deletion of the old readers and
`_merge_provider_files`, rollback tests, installed-wheel run.
(c) coding_lsp, memory, planning, gateway: one PR each, where each component's authority is
isolated, deleting its shard use; the last of these deletes the generic shard code in `state.py`.
Every PR passes architecture, config-inventory and installed-wheel checks.

## Code Samples & Guidance



## Files



## Validation

Unit and architecture tests (config inventory), migration and rollback tests, an installed-wheel run of config migrate on a legacy project fixture.

## Effort & Risk



## Standards

docs/design/configuration-model.md (phased spec); docs/standards/ARCHITECTURE_STANDARDS.md and ARCHITECTURE_GUIDELINES.md: one configuration authority, foundation owns mechanics and components own their sections, no parallel loaders, no compatibility paths without an approved obligation, delete obsolete code in the same change, evidence-led scope.

## Acceptance Criteria

The path-builders list in tests/unit/architecture/config_inventory.yaml is empty; no component keeps a second persisted authority for provider policy or options; config migrate converts existing projects with backup and has a tested rollback; user-project scope has precedence, isolation and conflict tests.

## Notes

Created 2026-10-31 after a GPT on-track review (verdict ADJUST): CFG09 is the critical dependency for closing CFG10 and CFG06; CFG10 completion is gated on this item and resolver coverage across supported entrypoints.

Progress 2026-10-31 (merged unless stated; every move ships `audiagentic config migrate` preview/--apply/--rollback with verified backups and compare-and-swap rollback):
- Implementation `enabled` flags: the feature shards were gitignored per-host files, so the flag is lifecycle state, now a local observation (#284). `providers.<id>.enabled` stays the user's override; migrate never writes it.
- Providers: options in `providers.<id>`, reconciliation mode/allowlist in `reconciliation`, install/access modes derived from the descriptor, decisions as local state (#285). Model sources (#287). Harness + Pi (`harness`, #288). Logging (`logging`, #289; `silenced`/`redact_patterns` stay additive so a redaction default cannot be dropped). Launch switches and locale (`launch`, `locale`, #290). Event layer, event triggers, prompt syntax (`events`, `event-triggers`, `prompt-syntax`, #291, in review).
- Path-builders: the inventory list is empty; `foundation.paths.names` is the path service (#286). `load_layered_config`/`load_layered_mapping` are deleted (#290); composition is a packaged table with no override.
Status after #294: done are the provider shard, provider options and policy, model sources, harness and Pi, logging, launch and locale, event layer/triggers/prompt syntax, the machine gpt-auto override, the per-component option/feature shards (user-project scope, #294), the user-project scope, the empty path-builders list and the deleted layered loader. Classified as state, not configuration, and left in place: the `.audiagentic/components/*.yaml` installation markers (version, installed-at, files). Still open:
1. `.audiagentic/config/project.yaml` (project identity legacy source, `prompt-launch` defaults, MCP onboarding bindings, and its use as the "managed project" marker): not in the original list, but still a legacy reader; decide whether identity and prompt-launch policy move to `project` / `prompt-launch` settings and the bindings become local state.
2. An installed-wheel run of `audiagentic config migrate` on a legacy project fixture (the item's validation line).
3. Close the item once 1 and 2 are done or explicitly deferred.
Decided: the shared-gateway server, node and connector documents stay explicit role documents (configuration-model.md, "Shared gateway role documents (kept)"; docs-only PR #297). Moving them would mean rewriting the node-grant revoke path, an explicit-scope settings writer and a gateway migration, for consistency only. Deferred, not complete; revisit if those documents must be layered or if their credential and loopback validation is ever shared. The project connector binding stays the `connector-config` path in the agents component state. Item 3 of the remaining list is done: component options and feature state are the `features` section of the user-project scope (#294); the user-project scope itself is done (#294); the machine gpt-auto override is done (#293).

Installed-wheel evidence 2026-10-31 (audiagentic 0.50.2 built from main 4bcadf123 into a throwaway venv, isolated HOME/XDG, legacy fixture of 7 files: provider file, provider policy, model sources, logging, harness ag.yaml, two feature shards): `config migrate` previewed '13 setting(s) and 1 local-state value(s) from 7 legacy file(s)'; `doctor` raised settings.legacy-files; `--apply` wrote the project settings, the user-project file (proj.yaml) and the enabled observation and removed the sources; `config show providers.codex / harness.endpoint.url / logging.level --origin` resolved each from the project settings with file and line; `--rollback <manifest>` restored all 22 items with 0 kept and the original files returned. The CI-side gap found on the way: tests/integration/runtime/conftest.py set AUDIAGENTIC_REPO_ROOT at import time and leaked into other tests (fixed in #295).

Project file 2026-10-31: `.audiagentic/config/project.yaml` is retired. Identity is `project.id` / new `project.name`; `prompt-launch` defaults are a new agent-jobs `prompt-launch` section (user, user-project, project, explicit); MCP onboarding bindings are a new project-component `mcp-onboarding` section (project scope), written by the explicit MCP install through the settings writer. The 'managed project' marker is the installation marker `.audiagentic/components/project.yaml` (`is_managed_project`). Dropped as unread: workflow-profile, tracked-docs-root, runtime-root, release-strategy, workflow-overrides (and the three matching project-context keys). The `project-config` contract (schema, canonical id, four fixtures) is retired. `config migrate` moves the file and rolls back; an unknown key refuses. Behaviour change: reconcile does nothing until bindings are recorded (no more 'use an explicit install to migrate' warning for legacy projects without a mcp-onboarding block). Remaining for CFG11: nothing in code; close once this lands.

## Change Log

- 2026-10-31T03:41:56.742276+00:00 (created-by): Created by agent
- 2026-10-31T07:10:56.461512+00:00 (updated-by): Updated: section:notes
- 2026-10-31T09:02:09.387618+00:00 (updated-by): Updated: section:notes
- 2026-10-31T10:51:22.402450+00:00 (updated-by): Updated: section:notes
- 2026-10-31T12:16:38.137875+00:00 (state-transition): State: pending → completed
