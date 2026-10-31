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

# One explicit gateway connection authority: the connector document

## Description

One standalone connection can be defined in three places today and the highest silently wins: the settings pair gateway.endpoint/gateway.token.file (added by CFG10, hours old), the project component-state connector-config path, and the plain component-state endpoint/token-file options. Make the connector document the only explicit connection definition and delete the other two, readers and writers, with no compatibility path. Automatic embedded selection needs no connector. Extend the connector endpoint to allow http://127.0.0.1:PORT and http://[::1]:PORT (the server's native loopback origin) and https elsewhere; reject every other http origin. Keep the existing redirect rejection. Migrate existing component-state options to a connector document without inventing a server id; fail with the exact fix when the pinned identity is missing.

## Steps

- Inventory every reader and writer of the settings pair and the plain component-state options (client.py, management_api, select-implementation, doctor, status, tests, docs)
- Delete gateway.endpoint and gateway.token.file from the schema and consumers
- Remove the plain endpoint/token-file branch and its writers; keep connector-config as the binding
- Connector schema: loopback http (explicit port, literal 127.0.0.1 or [::1]) or https; reject localhost, other hosts, userinfo, path, port 0, non-canonical IPv4
- One-shot migration of component-state options through config migrate where it can build a complete connector; otherwise fail with instructions

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Schema, selection, migration and integration tests; hermetic, never restarting the live shared gateway.

## Effort & Risk



## Standards

docs/design/configuration-model.md (Shared gateway setup); docs/standards/ARCHITECTURE_STANDARDS.md: one configuration authority per fact, no compatibility paths, delete obsolete readers and writers in the same change, no new AUDIAGENTIC_* variables, secrets only by file reference.

## Acceptance Criteria

- No duplicate connection field or reader remains (repository-wide obsolete-symbol search)
- Embedded mode works with no connector; explicit loopback http and remote https connectors work
- http to a non-loopback origin and any redirect fail
- Migration is idempotent, never overwrites a valid connector, never invents a server id
- gateway connect remains a complete path for users who lose the old sources

## Notes

Partly reverses the settings half of CFG10 (#308). Release gate: no release may remove the old sources unless a user can still create a working connector.

Trigger: one connection has three sources and the highest silently wins (CFG10 added the third). Partly reverses the settings half of CFG10 (#308). Standards: ARCHITECTURE_STANDARDS 4 and GUIDELINES 9 require callers migrated and the obsolete API, shim and compatibility test deleted in the same change, searching dotted-path strings, patches and dynamic imports too; no new AUDIAGENTIC_* variable. Register new error codes in error-resolutions.yaml. State exact validation scope. Release gate: no release may remove the old sources unless a user can still create a working connector (gateway connect with a hand-written connector remains a complete path).

## Change Log

- 2026-10-31T23:04:02.314327+00:00 (created-by): Created by claude
- 2026-10-31T23:04:34.949947+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:06:57.276584+00:00 (updated-by): Updated: section:standards
- 2026-10-31T23:09:46.806307+00:00 (updated-by): Updated: section:notes
