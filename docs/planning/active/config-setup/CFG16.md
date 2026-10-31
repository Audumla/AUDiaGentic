---
id: CFG16
order: 0
plan: config-setup
state: pending
created-at: '2026-10-31T23:04:07.737996+00:00'
breadth: ''
skill: advanced
created-by: claude
priority: P1
work: M
---

# Server roots and principal defaults

## Description

Simplify `server.yaml`. `projects` becomes an optional list of root paths; when omitted the server serves the project containing its working directory, resolved once at start. Each served project must have a declared project.id (read with foundation resolve_settings_cached(root).get('project.id')); a missing id or two roots with the same id is an actionable error. A principal's `projects` omitted means all configured roots, `[]` means none; `actions` omitted means all four existing actions (read, submit, cancel, session), documented in the schema and guide, unversioned. Unknown project ids and actions are rejected. Existing explicit lists migrate unchanged. No command-line root options (keyword-only CLI), registry, discovery, wildcard machinery or path-overlap analysis.

## Steps

- Change the server schema and loader: optional list of root paths; read declared ids; reject missing and duplicate ids
- Capture the working-directory default once at startup
- Principal defaults: omitted projects = all roots, [] = none, omitted actions = the four existing actions; reject unknown ids and actions
- Migrate the old projects map shape to the new one without changing any explicit permission; require an explicit operator decision if that cannot be established
- Keep node revoke preserving the roots and unrelated content under its existing lock and digest check; update shared-gateway.md; register new error codes

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

One-project and two-project configuration tests, duplicate-id tests, permission-default tests, migration tests, revoke test on the new shape.

## Effort & Risk



## Standards

docs/design/configuration-model.md (Shared gateway setup); docs/standards/ARCHITECTURE_STANDARDS.md 4 and GUIDELINES 9: delete the old map shape and its tests with the callers in the same change; GUIDELINES 7: one owner for the server document.

## Acceptance Criteria

- Single-project local setup needs no manually entered root
- Each additional initialized project needs one root entry
- Missing or duplicate project ids produce actionable errors
- Omitted permission fields have deterministic documented meanings
- Unknown project ids and actions are rejected
- Existing explicit permissions are not broadened by migration

## Notes

Depends on CFG13; sequence after CFG15 for end-to-end qualification. A project id change after admission must fail closed until grants are reconciled.

Trigger: roots and ids are typed per project and repeated in grants, node workspaces and the connector; the gateway CLI is keyword-only and cannot take --project. Depends on CFG13; sequence after CFG15 for end-to-end qualification. A project id change after admission must fail closed until grants are reconciled. Standards: the old map shape is deleted with its callers and tests in the same change (STANDARDS 4, GUIDELINES 9); the server document keeps one owner, so revoke must preserve the roots and unrelated content under its existing lock and digest check (GUIDELINES 7); register new error codes.

Agreed with GPT (round 7). Trusted operators on a shared server: grants are not a tenant boundary. Depends on CFG15.

## Change Log

- 2026-10-31T23:04:07.737996+00:00 (created-by): Created by claude
- 2026-10-31T23:04:39.935680+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:07:02.193136+00:00 (updated-by): Updated: section:standards
- 2026-10-31T23:09:52.257948+00:00 (updated-by): Updated: section:notes
- 2026-10-31T23:14:30.183054+00:00 (updated-by): Updated: section:description, section:steps, section:standards, section:acceptance_criteria
- 2026-10-31T23:30:33.748431+00:00 (updated-by): Updated: section:title, priority='P1', section:description, section:steps, section:validation, section:standards, section:acceptance_criteria, section:notes
