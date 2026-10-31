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
