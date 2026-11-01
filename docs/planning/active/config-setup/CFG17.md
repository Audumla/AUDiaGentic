---
id: CFG17
order: 0
plan: config-setup
state: pending
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

- Existing project-scoping keys are inventoried
- Requests and sessions remain project-specific
- Idempotency and conversation operations cannot cross project boundaries
- Execution uses the selected project's root and context
- Two-project tests show no cross-talk
- Any correctness defects found are fixed before shared multi-project sign-off

## Notes

Independent of CFG13-CFG16 and can start now. It gates any claim of project isolation, not the configuration work. Project code runs with the server's OS identity today unless the execution layer enforces otherwise: verify and record.

Agreed with GPT (round 7). The inventory can start now; final two-project sign-off follows CFG16. Not a security programme.

## Change Log

- 2026-10-31T23:14:22.736586+00:00 (created-by): Created by claude
- 2026-10-31T23:14:32.639039+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:standards, section:acceptance_criteria, section:notes
- 2026-10-31T23:30:36.227952+00:00 (updated-by): Updated: section:title, work='S', priority='P2', section:description, section:steps, section:validation, section:standards, section:acceptance_criteria, section:notes
- 2026-11-01T00:32:15.350417+00:00 (updated-by): Updated: section:effort_risk
