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

- Slice 1 (done in this PR): the shared client accepts literal loopback http://127.0.0.1:PORT (the shared server listens on loopback http only; TLS is the proxy's job) with the server-id check, bearer token and redirect rejection unchanged; https stays verified for every other host
- Slice 2 (cutover, one PR so no release carries two sources or none): connector document gets `mode: plain|shared`; plain = literal loopback http + token-file only; shared = server-id required, project-id REMOVED (taken from the local project's declared project.id via foundation resolve_settings_cached), https or loopback http, ca-file, source-node-config; new user/explicit setting `gateway.connector` (path to the document) is the only explicit binding; `gateway connect config FILE` validates, does the health handshake, then writes the setting through the existing config writer (project PATH removed from the grammar)
- Same PR deletes: gateway.endpoint and gateway.token.file (schema, client.py _explicit_connection and both branches, _uses_shared_connector pair test), component-state endpoint/token-file/connector-config options and their writers (management_api validate_standalone_config plain branch, gateway_connect_config popping), the standalone.yaml connection option keys, the agent_gateway_set_config connection keys; the standalone options schema becomes empty
- Rewrite CFG-AGSV-001: standalone selected but no valid connector configured; run: audiagentic gateway connect config FILE; keep specific errors for malformed documents, unreadable token files and failed authentication
- A plain connection serves one project: document it as single-project and refuse a mismatch where detectable; do not invent shared identity semantics for plain
- Slice 3: docs (shared-gateway.md, configuration-model.md, config_inventory.yaml), a documented one-time conversion for existing connectors and component-state users (no automatic migration machinery; the settings pair is hours old), hermetic multi-project qualification
- Rewrite tests: test_gateway_connector_selection.py, test_agents_gateway_management_api.py, settings schema tests, gateway connect CLI tests, standalone client tests; never the operator's real settings or the live shared gateway

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

Design agreed with GPT in round 8 (Option B: one machine-level connector pointer, project id from the local project; explicit mode field; shared over loopback http). Differences from GPT's slice order: its order put the connect command after the cutover, which would leave no way to bind a connection; connect and the setting ship in the cutover PR. [::1] is not accepted: the server only binds 127.0.0.1. Pre-implementation checks done for slice 1: shared identity headers/health server-id check are transport-independent; get_gateway_client is called with a project root almost everywhere. Still to verify in slice 2: resolve_settings_cached invalidation after the connect write, gateway_connect_config lock scope, callers that pass no project root.

## Change Log

- 2026-10-31T23:04:02.314327+00:00 (created-by): Created by claude
- 2026-10-31T23:04:34.949947+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:06:57.276584+00:00 (updated-by): Updated: section:standards
- 2026-10-31T23:09:46.806307+00:00 (updated-by): Updated: section:notes
- 2026-10-31T23:30:28.805567+00:00 (updated-by): Updated: section:title, section:description, section:steps, section:validation, section:standards, section:acceptance_criteria, section:notes
- 2026-10-31T23:50:15.340783+00:00 (updated-by): Updated: section:steps, section:notes
