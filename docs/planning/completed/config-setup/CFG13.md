---
id: CFG13
order: 0
plan: config-setup
state: superseded
created-at: '2026-10-31T23:03:59.378738+00:00'
breadth: ''
skill: advanced
created-by: claude
priority: P1
work: S
---

# Declared project identity for shared-gateway authorization

## Description

Cancelled (2026-11-01). A standalone declared-only project identity reader and hardening was a security-weighted design; the user's priority is easy setup, easy maintenance and no duplicated config, with only base security in a shared environment. Kept from it: served projects need a declared project.id (gateway init writes it once into the tracked project scope when absent, using the existing config writer; the gateway reads it with foundation resolve_settings_cached(root).get('project.id')), and duplicate ids among roots are rejected. Those belong to CFG15 and CFG16. Derived ids (origin repository name, directory name) are only the suggestion init writes.

## Steps

- Add a foundation reader of the literal `project.id` key in the project's tracked project scope only: no layered resolution, includes, interpolation or fallback identity (foundation/config/settings.py _declared_project_id reads user and project scopes today)
- Return the id or a precise failure: absent, user-only, explicit-only, derived only, malformed
- Canonicalize roots before comparing; reject overlapping, aliased and duplicate-id roots
- Reject a higher-layer value that conflicts with the declaration when used for gateway admission
- Register every new public error code in error-resolutions.yaml before use (GUIDELINES 3)
- Error text: no declared project.id in tracked settings; how to declare it; derived ids are not valid for shared-gateway authorization

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Plan cross-reference: CFG15 and CFG16 carry the retained requirements.

## Effort & Risk



## Standards

docs/design/configuration-model.md (Shared gateway setup); docs/standards/ARCHITECTURE_STANDARDS.md: one identity authority, reuse the existing settings provenance, no second algorithm, evidence-led scope.

## Acceptance Criteria

- Superseded by CFG15 (stable id creation) and CFG16 (served-project id resolution and duplicate rejection)
- No standalone identity reader, collision framework or overlap analysis is built

## Notes

Prerequisite for CFG15 and CFG16. Independent of CFG14. Design record: docs/design/configuration-model.md, Shared gateway setup. Decided after three GPT review rounds; the keyword-only gateway CLI rejects --options.

Trigger: the shared gateway must not authorize from provisional ids, and CFG15/CFG16 need one id entered once. Prerequisite for CFG15 and CFG16; independent of CFG14. Design record: docs/design/configuration-model.md, Shared gateway setup. Decided after three GPT rounds; then checked against ARCHITECTURE_STANDARDS, ARCHITECTURE_GUIDELINES, SECRETS_MANAGEMENT and CI_RELEASE_GATES (standards review changed placement: foundation, not the project component, because only providers is an approved cross-component API). Deferred variants: repository attestation, per-checkout workspace selectors.

Trigger: the shared gateway must not authorize from provisional ids (origin repository name, main checkout, directory name), and CFG15/CFG16 need one id entered once. Prerequisite for CFG15 and CFG16; independent of CFG14. Design record: docs/design/configuration-model.md, Shared gateway setup. Decided after five GPT rounds and a check against ARCHITECTURE_STANDARDS, ARCHITECTURE_GUIDELINES, SECRETS_MANAGEMENT and CI_RELEASE_GATES (placement is foundation, not the project component, because only providers is an approved cross-component API).

Agreed with GPT in round 7: the plan of record is CFG14, CFG15, CFG16, CFG17 (P2) and CFG12 unchanged.

## Change Log

- 2026-10-31T23:03:59.378738+00:00 (created-by): Created by claude
- 2026-10-31T23:04:32.417527+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:06:54.802508+00:00 (updated-by): Updated: section:standards
- 2026-10-31T23:09:43.659951+00:00 (updated-by): Updated: section:steps, section:notes
- 2026-10-31T23:14:25.206806+00:00 (updated-by): Updated: section:steps, section:acceptance_criteria, section:notes
- 2026-10-31T23:30:23.820414+00:00 (state-transition): State: pending → superseded
- 2026-10-31T23:30:26.340109+00:00 (updated-by): Updated: section:description, section:validation, section:acceptance_criteria, section:notes
