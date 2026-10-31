---
id: CFG11
order: 0
plan: config-setup
state: pending
created-at: '2026-10-31T03:41:56.742276+00:00'
breadth: ''
skill: advanced
created-by: agent
work: L
priority: P1
---

# CFG09 phase 2: migrate the remaining readers and path-builders, config migrate

## Description

CFG09 was completed for phase 1 only (agent catalog, gateway settings). This item carries the phase 2 remainder so it has an active owner: the ~46 modules in tests/unit/architecture/config_inventory.yaml path-builders that join .audiagentic paths themselves, the remaining legacy readers (model sources PC12, provider option files, interoperability, component markers, logging, shared server/node config), `audiagentic config migrate` with backup and rollback, and user-project scope. The provider feature-state shard (providers.yaml: enabled, options, per-feature state) and the per-provider option files are one migration with one contract. Legacy readers stay only until migration and rollback tests pass; no compatibility paths without an approved obligation.

## Steps

1. Inventory the provider shard (enabled, options, per-feature state) and every consumer across providers, coding_lsp, memory, planning and gateway; define destination settings keys, precedence, migration, rollback and removal criteria; GPT review.
2. Migrate providers (shard and option files) onto settings with config migrate.
3. Migrate model sources, interoperability, component markers and logging, one subsystem per PR, deleting the old reader in the same PR.
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
`providers.<id>.enabled` policy: `false` always disables. `auto` evaluates at resolution
(reconciliation policy allows, host available, qualified where required) and is never persisted.
`true` permits activation, still subject to runtime gates (host available). The legacy feature-level
`enabled: false` is not a separate veto: migrate converts a legacy explicit false to policy
`false` and a legacy explicit true to policy `true` when no policy exists; if both exist and
conflict, migrate refuses and lists the conflict for the user to resolve.

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

## Change Log

- 2026-10-31T03:41:56.742276+00:00 (created-by): Created by agent
