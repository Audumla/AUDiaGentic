---
id: CFG14
order: 0
plan: config-setup
state: pending
created-at: '2026-10-31T23:04:02.314327+00:00'
breadth: ''
skill: advanced
created-by: claude
priority: P1
work: M
---

# Single explicit connection authority: the connector document

## Description

Make `connector.yaml` the sole authority for an explicit client-to-gateway connection. Today one connection has three sources and the highest silently wins: the settings pair gateway.endpoint/gateway.token.file (added by CFG10), the component-state connector-config path, and the plain component-state endpoint/token-file options. Delete the settings pair and the plain options, updating every caller; keep connector-config as the project binding. Automatic embedded operation needs no connector. Allow `http://127.0.0.1:PORT` and `http://[::1]:PORT` (the server's native loopback origin) and keep https and the existing redirect rejection. One-time migration of existing state; when a connector cannot be built unambiguously, fail with the exact fix. No compatibility readers.

## Steps

- Inventory every reader and writer of the settings pair and the plain component-state options (client.py, management_api, select-implementation, status, tests, docs)
- Delete gateway.endpoint and gateway.token.file from the schema and consumers; remove the plain endpoint/token-file branch and its writers
- Connector endpoint: allow literal loopback http, keep https; keep existing redirect rejection
- Migrate existing component-state options to a connector document where unambiguous; otherwise print the fix
- Update docs and tests; search production, tests, config and dotted-path strings for removed symbols

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Configuration migration tests, connection tests, repository-wide search for the removed readers, local and remote smoke tests against an isolated gateway (never the live shared gateway).

## Effort & Risk



## Standards

docs/design/configuration-model.md (Shared gateway setup); docs/standards/ARCHITECTURE_STANDARDS.md 4 and ARCHITECTURE_GUIDELINES 9: migrate callers and delete the obsolete API and tests in the same change; no new AUDIAGENTIC_* variable; register new error codes.

## Acceptance Criteria

- Exactly one explicit client connection authority remains
- Obsolete settings, component-state options and callers are removed
- Embedded and automatic operation are unchanged
- Loopback http and existing https connections work
- Migration handles unambiguous configurations and explains ambiguous ones
- Existing tests and documentation reflect the new contract

## Notes

Partly reverses the settings half of CFG10 (#308). Release gate: no release may remove the old sources unless a user can still create a working connector.

Trigger: one connection has three sources and the highest silently wins (CFG10 added the third). Partly reverses the settings half of CFG10 (#308). Standards: ARCHITECTURE_STANDARDS 4 and GUIDELINES 9 require callers migrated and the obsolete API, shim and compatibility test deleted in the same change, searching dotted-path strings, patches and dynamic imports too; no new AUDIAGENTIC_* variable. Register new error codes in error-resolutions.yaml. State exact validation scope. Release gate: no release may remove the old sources unless a user can still create a working connector (gateway connect with a hand-written connector remains a complete path).

Agreed with GPT (round 7). Partly reverses the settings half of CFG10 (#308). Release gate: no release may remove the old sources unless a user can still create a working connector (gateway connect with a hand-written connector stays a complete path). Dependencies: none.

## Change Log

- 2026-10-31T23:04:02.314327+00:00 (created-by): Created by claude
- 2026-10-31T23:04:34.949947+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:06:57.276584+00:00 (updated-by): Updated: section:standards
- 2026-10-31T23:09:46.806307+00:00 (updated-by): Updated: section:notes
- 2026-10-31T23:30:28.805567+00:00 (updated-by): Updated: section:title, section:description, section:steps, section:validation, section:standards, section:acceptance_criteria, section:notes
