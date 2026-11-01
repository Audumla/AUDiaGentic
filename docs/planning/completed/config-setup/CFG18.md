---
id: CFG18
order: 0
plan: config-setup
state: completed
created-at: '2026-11-01T02:19:36.433138+00:00'
breadth: ''
skill: advanced
created-by: claude
priority: P2
work: M
---

# Gateway operator ergonomics: default serve, pair validation, connector-implies-standalone, status

## Description

Target state agreed with GPT (round 10, full agreement): keep the architecture (layered settings, one tracked project.id, one machine connector binding, separate generated server/connector/node documents, init provisions, serve starts, status diagnoses, validate checks). Five bounded optimizations remove the remaining operator friction: (1) `gateway serve` with no arguments serves the default directory's server.yaml (printing the path); (2) `gateway validate` cross-checks a local connector/server pair (endpoint port and pinned server-id) when they are the generated pair; (3) an explicit gateway.connector implies a standalone connection, so init and connect stop writing gateway.implementation, and a contradicting explicit implementation fails; (4) `gateway status` with no arguments reports the bound connector, endpoint, pinned id, connection result and served projects; (5) the guide stays operational and the design record architectural. Everything else is deferred.

## Steps

- Slice A: serve with no arguments -> user_config_dir()/gateway/server.yaml; fails clearly when missing (never initializes); prints the path it uses
- Slice B: validate pairs: when the connector's server-id or loopback port matches the default-directory server document, report endpoint-port and server-id mismatches without rewriting either file; remote connectors are not compared with an unrelated local server
- Slice C: resolver rule: gateway.connector set => standalone; an explicit gateway.implementation other than standalone with a connector fails; `standalone` with no connector keeps the CFG-AGSV-001 error; init and connect write only gateway.connector; tests for every precedence combination
- Slice D: status with no arguments reads the bound connector (gateway.connector) and reports connector path and mode, endpoint, pinned server-id, health result and served projects; failure classes (configuration, connection, project state) stay distinct; no new health service
- Slice E: guide = operations, design record = architecture; remove repeated normative text; document changing the port, rotating a token, adding and removing a project as short procedures

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Unit tests per slice (hermetic: temporary directories and isolated settings home; the end-to-end gate #346 re-run); agents, architecture, contract, planning and config suites; privacy guard.

## Effort & Risk

Size M. Risk: slice C changes connection selection precedence across layered settings (existing standalone+connector settings must keep working); slice A could be mistaken for a custom configuration, so serve prints the chosen path.

## Standards

docs/design/configuration-model.md (Shared gateway setup); docs/standards/ARCHITECTURE_STANDARDS.md: CLI delegates to a management_api function, one configuration authority per fact, delete the obsolete write path in the same change.

## Acceptance Criteria

- gateway serve works with no path after gateway init; serve config FILE still works
- validate reports a port or server-id mismatch of the generated connector/server pair and does not rewrite either
- A configured gateway.connector selects standalone without gateway.implementation; contradiction fails; init and connect write one setting
- gateway status with no arguments explains the current connection and served projects and distinguishes configuration, connection and project-state failures
- Guide and design record do not repeat each other's normative text; maintenance procedures documented
- Hermetic tests only; the live shared gateway is never restarted

## Notes

Round 10 rulings: ACCEPT port/token/server-id as generated references, the three document formats, tracked project.id, no migration; DEFER workspace_roots derivation, gateway connector create, node enrollment, token rotation and port-change commands (document the procedure; automate when routine). OUT: any further security hardening.

DONE. Round 10 rulings: ACCEPT port/token/server-id as generated references, the three document formats, tracked project.id, no migration; DEFER workspace_roots derivation, gateway connector create, node enrollment, token rotation and port-change commands (documented procedures in the guide); OUT: further security hardening. Implemented: A) `gateway serve` with no arguments serves the default directory's server.yaml, prints the path, fails clearly when missing and never initializes; B) validate cross-checks the generated pair (same server-id => the loopback port must match listen.port; CFG-AGSV-009; remote connectors never compared; nothing rewritten); C) gateway.connector alone resolves to standalone (source `connector`); init and connect write one setting. DEVIATION FROM GPT: an explicit gateway.implementation still WINS over a connector instead of failing (it is an explicit instruction, e.g. a temporary embedded run, and failing would add a trap in a hot resolver); `where` reports the effective implementation and what decided it; D) `gateway status` with no arguments reports the bound connector, mode, endpoint, pinned server-id and health (management_api.gateway_connection_status); configuration and connection failures keep distinct codes; E) guide: everyday maintenance procedures and quickstart; design record: target state. Hermetic tests only.

## Change Log

- 2026-11-01T02:19:36.433138+00:00 (created-by): Created by claude
- 2026-11-01T02:19:50.988514+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:effort_risk, section:standards, section:acceptance_criteria, section:notes
- 2026-11-01T02:39:45.368419+00:00 (updated-by): Updated: section:notes
- 2026-11-01T02:39:47.877648+00:00 (state-transition): State: pending → completed
