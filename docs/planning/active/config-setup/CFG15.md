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

- Order: after CFG16-A/B so init writes the final server.yaml shape
- gateway init [dir PATH] [project PATH] [dry-run] through management_api: default dir user_config_dir()/gateway/ (server.yaml, connector.yaml, credentials/ 0700 with operator.token 0600); fixed port 8765; server-id gw- plus 16 random hex; server.yaml with an explicit absolute `projects` root and a principal with projects/actions omitted; shared-mode loopback connector (http://127.0.0.1:8765, server-id pinned, token-file relative); exclusive creation, no overwrite, staged validation with the production loaders, then publish; dry-run generates and shows no credential
- project.id: require a project root (git worktree or existing AUDiaGentic project); preserve and validate an existing declared id; otherwise show the derived suggestion in dry-run and write it once to the tracked project scope; reject collisions; a server-only host is refused with an actionable message
- Bind: write gateway.connector and gateway.implementation=standalone to the user settings only when gateway.connector is unset (same binding: nothing; different: preserve and print the switch command; incompatible implementation: report, never silently change); no handshake in init
- Idempotence table: all absent create; all present and consistent no-op; existing valid files with binding absent bind only; any partial, invalid or inconsistent set refuse and list; no healing, no token rotation; an interrupted run is reported by the next run, no rollback framework
- gateway where (offline): default dir and which files exist, effective gateway.connector (path, mode, endpoint, server-id), implementation and winning scope/source, current project's declared id (or derived and not declared), served roots and ids; never a token, never the network; succeeds when files are missing or invalid
- gateway validate server config FILE [project PATH] (roots exist, declared ids, duplicates, grants, actions, credentials, port/endpoint agreement when the pair is checked) and validate connector (loader, files, project.id presence when shared); out of scope: reachability, TLS, proxies, remote state, port availability, live authentication
- Update shared-gateway.md setup to: gateway init, then gateway serve config FILE; register new error codes, reusing existing ones where the meaning matches

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

Agreed with GPT (rounds 7 and 9). CFG15-A (init) implemented in this change: management_api.gateway_init -> service/init_setup.py; CLI `gateway init [dir PATH] [project PATH] [dry-run]`; codes CFG-AGSV-007 (partial/inconsistent existing setup) and CFG-AGSV-008 (needs a project / invalid id) registered. Creation is create-then-validate with removal of only this run's files on failure (not a transaction; an interrupted run is reported by the next). CFG15-B (gateway where + validate extension) and CFG16-C (end-to-end gate) follow. Known limit: if the files already exist but the project has no declared project.id, the existing-file check reports the missing id (declare it with config set, then rerun). A declared project.id that is not a valid gateway id (lowercase) is refused with the fix. Base security only: authentication required, 0600 token files in a 0700 directory, loopback bind, no overwrite of credentials. Deferred: connector create, node enrollment, registry, discovery.

Agreed with GPT (rounds 7 and 9). CFG15-A (gateway init, #338) merged. CFG15-B implemented in this change: `gateway where [project PATH] [output json]` (management_api.gateway_where -> service/where_report.py; offline, never a token, reports missing/invalid files as status) and `gateway validate server|node|connector config FILE [project PATH]` through management_api.gateway_validate_deployment (server loader already resolves roots, declared ids, duplicates and grants after CFG16-A; omitted roots use project/cwd; a shared connector needs the project's declared project.id). Out of scope and documented: reachability, TLS, proxies, port availability, live authentication; the connector-endpoint/server-port agreement check was not added (a generated pair is consistent and a hand edit is caught by status/connect dry-run). Remaining for the CFG14-17 aim: CFG16-C end-to-end gate (init -> validate -> serve -> request, restart, cross-project negative) and CFG17.

## Change Log

- 2026-10-31T23:04:05.088135+00:00 (created-by): Created by claude
- 2026-10-31T23:04:37.477965+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:06:59.749542+00:00 (updated-by): Updated: section:standards
- 2026-10-31T23:09:49.552513+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:14:27.715171+00:00 (updated-by): Updated: section:steps, section:acceptance_criteria
- 2026-10-31T23:30:31.272919+00:00 (updated-by): Updated: section:title, section:description, section:steps, section:validation, section:standards, section:acceptance_criteria, section:notes
- 2026-11-01T00:32:12.911787+00:00 (updated-by): Updated: section:effort_risk
- 2026-11-01T00:32:30.124289+00:00 (updated-by): Updated: section:notes
- 2026-11-01T00:50:59.486071+00:00 (updated-by): Updated: section:steps
- 2026-11-01T01:04:59.559061+00:00 (updated-by): Updated: section:notes
- 2026-11-01T01:30:37.720099+00:00 (updated-by): Updated: section:notes
