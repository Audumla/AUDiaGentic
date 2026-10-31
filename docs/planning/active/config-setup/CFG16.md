---
id: CFG16
order: 0
plan: config-setup
state: pending
created-at: '2026-10-31T23:04:07.737996+00:00'
breadth: ''
skill: advanced
created-by: claude
priority: P2
work: M
---

# Minimal project-root selection for the shared gateway server

## Description

Operators currently type `projects: {id: path}` and repeat ids in every principal's grants, node workspaces and the connector. Under the trusted-operator model grants are not a tenant boundary, so simplify. `projects` becomes an optional list of root paths; each root's id is its declared project.id (CFG13). When omitted, `gateway serve` serves the project containing the working directory, resolved once at start; `projects: []` is invalid. A principal's `projects` omitted means all projects in the server's configured root list (frozen per loaded configuration, extended only by an explicit root change and reload); `[]` means none; an explicit list narrows; unknown ids fail. `actions` omitted means a versioned default set (read, submit, cancel, session), never an automatically expanding one; unknown actions fail. No command-line root options (the gateway CLI is keyword-only), no discovery, no registry. Failures surface at serve start and in `gateway validate server`.

## Steps

- Change the server schema and loader: optional list of root paths; canonicalize; read declared ids via CFG13
- Capture the working-directory default once at startup; document that supervised services should list explicit roots
- Principal grants: omitted projects = all configured, [] = none, explicit list narrows; omitted actions = the versioned default set
- Reject duplicate canonical roots, overlapping roots, duplicate ids, missing declarations, unknown project ids and unknown actions before serving
- Migrate the old `projects` map and explicit grants without broadening any principal's effective permissions; no compatibility reader
- Make revoke preserve roots and unrelated content under its existing lock and digest check

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Schema, cwd, canonical-path, grant and multi-project integration tests; revoke race tests unchanged.

## Effort & Risk



## Standards

docs/design/configuration-model.md (Shared gateway setup); docs/standards/ARCHITECTURE_STANDARDS.md: one configuration authority per fact, delete the old map shape and its tests in the same change, reuse the existing lock and digest-check writer for revoke, register new error codes.

## Acceptance Criteria

- One project served from its directory needs no root configuration
- Explicit multi-project roots work; each rejection above happens before serving
- Offline validation equals startup validation for deterministic checks
- Migration preserves every existing principal's effective project and action set (test)
- Adding a second project is one root line, then validate

## Notes

Depends on CFG13; sequence after CFG15 for end-to-end qualification. A project id change after admission must fail closed until grants are reconciled.

Trigger: roots and ids are typed per project and repeated in grants, node workspaces and the connector; the gateway CLI is keyword-only and cannot take --project. Depends on CFG13; sequence after CFG15 for end-to-end qualification. A project id change after admission must fail closed until grants are reconciled. Standards: the old map shape is deleted with its callers and tests in the same change (STANDARDS 4, GUIDELINES 9); the server document keeps one owner, so revoke must preserve the roots and unrelated content under its existing lock and digest check (GUIDELINES 7); register new error codes.

## Change Log

- 2026-10-31T23:04:07.737996+00:00 (created-by): Created by claude
- 2026-10-31T23:04:39.935680+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:07:02.193136+00:00 (updated-by): Updated: section:standards
- 2026-10-31T23:09:52.257948+00:00 (updated-by): Updated: section:notes
- 2026-10-31T23:14:30.183054+00:00 (updated-by): Updated: section:description, section:steps, section:standards, section:acceptance_criteria
