---
id: CFG15
order: 0
plan: config-setup
state: pending
created-at: '2026-10-31T23:04:05.088135+00:00'
breadth: ''
skill: advanced
created-by: claude
priority: P1
work: M
---

# Gateway init, validation and diagnostics

## Description

Generate setup instead of hand-writing it. `gateway init` creates the server id, one principal and its private token file, the server document and a same-machine loopback connector, and writes `project.id` into the project's tracked scope when absent (suggested from the git origin name or directory, shown in dry-run, never changing an existing value). An existing valid setup is reported, not an error; conflicting files or credentials are refused. `gateway validate server|node|connector config FILE` (PR #314, schema) also checks roots and references with actionable errors. A small read-only `gateway where` prints the default gateway directory, the document locations and the current project's bound connector (endpoint and server id, never tokens). A remote connector stays the five documented fields, validated by `gateway validate connector`; a `connector create` command is deferred.

## Steps

- gateway init: validate everything in memory first, then write; token by a private file (mode 0600, referenced by path); write server.yaml, connector.yaml and project.id; print the directory and next commands; dry-run
- Existing valid configuration is preserved and reported; conflicts are reported, never overwritten; a documented short recovery for a partial write, no transaction framework
- Extend gateway validate through a public agents API to check roots, project ids and references
- gateway where (keyword grammar): default directory, document paths, current project's bound connector
- Update shared-gateway.md setup checklist to the generated flow; register new error codes

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Fresh init, repeat init, dry-run, conflict, project rename, validate and local smoke tests in temporary directories with an isolated gateway on an ephemeral port; unit, contract and architecture suites; exact scope stated.

## Effort & Risk

Size M. Risk: surprising writes to tracked project settings (project.id) and to credentials; init must never overwrite or rotate existing identity or credentials; a partial multi-file write needs a documented short recovery, not a transaction framework.

## Standards

docs/design/configuration-model.md (Shared gateway setup); docs/standards/ARCHITECTURE_STANDARDS.md: CLI delegates to an agents public API (no loader imports in the adapter), foundation does not import agents, evidence-led scope; SECRETS_MANAGEMENT: tokens in private files by path, never printed, logged or passed as arguments.

## Acceptance Criteria

- A new local project needs zero hand edits and at most two setup commands (init, then validate and serve)
- project.id is written once and stays stable across moves and restarts
- Existing valid configuration is preserved; conflicts are reported
- Dry-run shows planned files and changes without revealing secrets
- Validation reports missing roots, references and malformed documents with the fix
- Effective document locations and the project's connector binding are discoverable with gateway where

## Notes

Depends on CFG13 and CFG14. Node enrollment, a project registry, directory discovery and wildcard principals are deliberately not part of this work (see the design record).

Depends on CFG13 and CFG14. Trigger: every setup needs the generated files; hand transcription of secrets and ids is the evidenced friction. DEFERRED variant (evidence-led scope): `gateway connector create`. Build it only if a measured remote walkthrough shows the five-field file fails the setup target; its trigger is that measurement. Also out of scope: node enrollment, project registry, directory discovery, wildcard principals, remote token transfer.

Agreed with GPT (round 7). Base security only: authentication required, 0600 token files, loopback bind, no overwrite of credentials. Served projects need a declared project.id read with foundation resolve_settings_cached(root).get('project.id') (any layer); no new reader. Depends on CFG14. Deferred: connector create, node enrollment, registry, discovery.

Agreed with GPT (round 7). CFG14 is done: the connector has mode plain|shared and no project-id; `gateway connect config FILE` sets the machine-level gateway.connector. So init writes a shared-mode loopback connector (http://127.0.0.1:PORT, server-id pinned, token-file) and project.id into the project's tracked scope when absent; init then runs or prints connect. Base security only: authentication required, 0600 token files, loopback bind, no overwrite of credentials. Served projects need a declared project.id read with foundation resolve_settings_cached(root).get('project.id') (any layer); no new reader. Deferred: connector create, node enrollment, registry, discovery.

## Change Log

- 2026-10-31T23:04:05.088135+00:00 (created-by): Created by claude
- 2026-10-31T23:04:37.477965+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:06:59.749542+00:00 (updated-by): Updated: section:standards
- 2026-10-31T23:09:49.552513+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:14:27.715171+00:00 (updated-by): Updated: section:steps, section:acceptance_criteria
- 2026-10-31T23:30:31.272919+00:00 (updated-by): Updated: section:title, section:description, section:steps, section:validation, section:standards, section:acceptance_criteria, section:notes
- 2026-11-01T00:32:12.911787+00:00 (updated-by): Updated: section:effort_risk
- 2026-11-01T00:32:30.124289+00:00 (updated-by): Updated: section:notes
