---
id: CFG17
order: 0
plan: config-setup
state: pending
created-at: '2026-10-31T23:14:22.736586+00:00'
breadth: ''
skill: advanced
created-by: claude
priority: P1
work: M
---

# Shared-gateway project separation audit and tests

## Description

Requirement (user, 2026-10-31): projects run on shared servers operated by people with access to all projects. Separation of running is required; communication between projects, and one project's settings affecting another or the server, are not wanted. Audit and prove application-level separation: inventory first, then hermetic two-project tests with one principal authorized for both, then fix only demonstrated gaps. Do not engineer an OS sandbox; state plainly that OS and filesystem isolation of project code is not guaranteed unless the execution layer enforces and verifies it.

## Steps

- Inventory (entry gate): request and session persistence keys and secondary indexes; idempotency scope and replay lookup; conversation creation, continuation and recovery namespace; server-side project context binding and whether request metadata can override it; node workspace selection and path containment; service-root storage, caches and logs; whether project code can reach other roots or server configuration
- Hermetic tests: two roots, distinct ids, one principal with both projects
- Fix demonstrated gaps only; no speculative storage redesign
- Document the isolation guarantee and its explicit non-guarantees in the design record and shared-gateway.md

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Hermetic tests with isolated state and ephemeral ports; never the live shared gateway. Unit, contract and architecture suites; exact scope stated.

## Effort & Risk



## Standards

docs/design/configuration-model.md (Shared gateway setup); docs/design/gateway-shared-service.md; docs/standards/ARCHITECTURE_STANDARDS.md: evidence-led scope, errors via registered AudiaGenticError codes, no secrets in results.

## Acceptance Criteria

- Two simultaneous executions each use their own root, context and state
- Identical conversation ids and idempotency keys in two projects share nothing
- Project A's context cannot read, cancel, retry, resume, adopt a session of, or trigger project B's work
- Project-supplied metadata cannot select another project's workspace; node dispatch for A cannot reach B's workspace
- Project A's settings cannot change server behaviour or project B's
- Each project restarts and recovers independently
- Within-project collaborative read (other principals' requests and sessions) is unchanged

## Notes

Independent of CFG13-CFG16 and can start now. It gates any claim of project isolation, not the configuration work. Project code runs with the server's OS identity today unless the execution layer enforces otherwise: verify and record.

## Change Log

- 2026-10-31T23:14:22.736586+00:00 (created-by): Created by claude
- 2026-10-31T23:14:32.639039+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:standards, section:acceptance_criteria, section:notes
