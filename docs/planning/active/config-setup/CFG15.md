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

# Gateway init and connector provisioning (no hand-written YAML)

## Description

Setup today is hand-written and hand-cross-referenced: random token files with exact modes, server.yaml, connector.yaml, matching ids. Generate them. `gateway init` creates a stable server id, one principal and its token file (exclusive create, private mode, no symlink following, never printed or passed as an argument), a validated server.yaml and, for the same machine, a loopback connector.yaml with the server id pinned and the project id read from the declared project.id (CFG13). It never overwrites or rotates existing identity or credentials, reports a complete init as a no-op, and has a dry-run. `gateway validate` resolves project ids and grants. Logic lives in an agents public API; the CLI only parses and prints (ARCHITECTURE_STANDARDS 8). A remote connector stays a validated five-field file; a `connector create` command is a deferred variant (below).

## Steps

- gateway init: resolve the project; if `project.id` is absent, write it to the project's TRACKED scope with the existing config writer (a one-time suggestion from the git origin name or directory, shown in dry-run); never change an existing valid value; fail on an invalid one
- Generate server id, one principal (projects and actions omitted, see CFG16) and its token by exclusive create in a private file; write server.yaml and a same-machine loopback connector; validate with the production loaders; print paths and next commands; support dry-run
- Token location and mode follow the existing convention (SECRETS_MANAGEMENT: private 0600 files, referenced by path, never in YAML values, arguments or logs)
- Partial failure: remove only files this invocation created; refuse an inconsistent existing set; never rotate identity or credentials
- gateway validate server|node|connector config FILE through a public agents API (not by importing shared_config from the CLI); server validation also resolves ids, roots and grants
- Update shared-gateway.md setup checklist to the generated flow; register new error codes

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Hermetic temporary-directory CLI tests, idempotency, dry-run, permission and secret-leak tests, and a local end-to-end connection to an isolated gateway on an ephemeral port. Unit, contract and architecture suites; state exact scope.

## Effort & Risk



## Standards

docs/design/configuration-model.md (Shared gateway setup); docs/standards/ARCHITECTURE_STANDARDS.md: CLI delegates to an agents public API, foundation does not import agents, secrets never printed or passed as arguments, evidence-led scope (no registry, enrollment framework or discovery).

## Acceptance Criteria

- One project, same machine: zero hand-edited files; commands: init, then validate and serve
- Remote: the connector is the five documented fields, checked by gateway validate connector and connect dry-run
- Rerun never changes server id, credentials or an existing project.id; dry-run writes nothing and shows the project.id it would write
- Token contents are never printed, logged or passed as arguments; modes verified in tests
- Tracked project settings cannot affect server configuration (test)
- Invalid identity, endpoint or missing credential fails with the exact fix

## Notes

Depends on CFG13 and CFG14. Node enrollment, a project registry, directory discovery and wildcard principals are deliberately not part of this work (see the design record).

Depends on CFG13 and CFG14. Trigger: every setup needs the generated files; hand transcription of secrets and ids is the evidenced friction. DEFERRED variant (evidence-led scope): `gateway connector create`. Build it only if a measured remote walkthrough shows the five-field file fails the setup target; its trigger is that measurement. Also out of scope: node enrollment, project registry, directory discovery, wildcard principals, remote token transfer.

## Change Log

- 2026-10-31T23:04:05.088135+00:00 (created-by): Created by claude
- 2026-10-31T23:04:37.477965+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:06:59.749542+00:00 (updated-by): Updated: section:standards
- 2026-10-31T23:09:49.552513+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:14:27.715171+00:00 (updated-by): Updated: section:steps, section:acceptance_criteria
