---
id: CFG17
order: 0
plan: config-setup
state: completed
created-at: '2026-10-31T23:14:22.736586+00:00'
breadth: ''
skill: advanced
created-by: claude
priority: P2
work: S
---

# Per-project running separation check

## Description

Projects run on a shared server operated by people who can reach all of them. Separation of running is required; interference between projects, and one project's settings changing the server or another project, are not wanted. Audit how requests, sessions, idempotency keys, conversations, workspace selection and execution state are keyed by project, add focused two-project tests, and fix demonstrated defects only. Document the guarantee as correct project scoping; do not claim OS-level or adversarial tenant isolation.

## Steps

- Inventory the existing project-scoping keys and lookups (request, session, idempotency, conversation, workspace selection, service-root storage)
- Two-project tests with one principal granted both: identical conversation ids and idempotency keys, cross-project read/cancel/resume attempts, independent restart
- Check that project settings cannot change gateway or other-project behaviour (the gateway section is user and explicit scope only)
- Fix demonstrated defects only; document the guarantee and the OS-isolation non-claim in shared-gateway.md

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Focused unit tests plus a two-project integration smoke test with independent sessions and requests on an isolated gateway; never the live shared gateway.

## Effort & Risk

Size S unless defects are found. Risk: existing runtime state may be shared across projects in a way that needs a real fix; project code runs with the server's OS identity, which is documented as a non-guarantee.

## Standards

docs/design/configuration-model.md (Shared gateway setup); docs/design/gateway-shared-service.md; docs/standards/ARCHITECTURE_STANDARDS.md: evidence-led scope, registered AudiaGenticError codes.

## Acceptance Criteria

- Existing project-scoping keys are inventoried (see notes): all request, session, idempotency, work and context state is under the project's own root
- Requests and sessions stay project-specific: identical ids and idempotency keys in two projects share nothing (test)
- A request cannot be read, listed or cancelled through another project (test)
- Execution uses the selected project's root: the ingress takes the root only from the server's project map (test; routing end to end in #346)
- Project settings cannot change the gateway or another project: the writer refuses a project gateway section and the gateway reader ignores one (test)
- No defect found; the OS-level isolation non-claim is documented in shared-gateway.md

## Notes

Independent of CFG13-CFG16 and can start now. It gates any claim of project isolation, not the configuration work. Project code runs with the server's OS identity today unless the execution layer enforces otherwise: verify and record.

Agreed with GPT (round 7). The inventory can start now; final two-project sign-off follows CFG16. Not a security programme.

DONE. INVENTORY: request records, timelines, observations, the idempotency index (hashed key), maintenance locks, sessions, and the agent work/context records all live under the project's own root (agents_paths.gateway_root / agent_work_root / agent_context_path derive from project_root); the shared ingress resolves a call's root only from the server's own project map (config.projects[project-id]) after checking the principal's project and action grants, and treats caller params as data (a project_root param does not select the root). The idempotency key is hashed with the principal only, not the project, which is safe because the index is per project root. The gateway settings section is read with machine_only (project scope never opened) and the writer refuses a project-scope gateway section. RESULT: no defect found; tests/unit/agents/test_gateway_project_separation.py proves identical idempotency keys, request ids and path builders share nothing, a request is not readable, listable or cancellable through another project, the ingress routes by the server map only, and a project file carrying a gateway section changes nothing. The end-to-end gate (#346) covers routing and a narrowed principal. KNOWN LIMITS (documented, not fixed): operator views (dashboard, known-projects registry) deliberately list across projects; project code runs with the server's OS identity, so OS/filesystem isolation is NOT claimed; SH60 (audiagentic2) changes Work identity keying and must keep the project id inside its delivery key.

## Change Log

- 2026-10-31T23:14:22.736586+00:00 (created-by): Created by claude
- 2026-10-31T23:14:32.639039+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:standards, section:acceptance_criteria, section:notes
- 2026-10-31T23:30:36.227952+00:00 (updated-by): Updated: section:title, work='S', priority='P2', section:description, section:steps, section:validation, section:standards, section:acceptance_criteria, section:notes
- 2026-11-01T00:32:15.350417+00:00 (updated-by): Updated: section:effort_risk
- 2026-11-01T01:51:53.742854+00:00 (updated-by): Updated: section:notes
- 2026-11-01T01:51:56.464383+00:00 (updated-by): Updated: section:acceptance_criteria
- 2026-11-01T01:53:39.391636+00:00 (state-transition): State: pending → completed
