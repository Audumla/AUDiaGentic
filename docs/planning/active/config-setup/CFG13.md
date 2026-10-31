---
id: CFG13
order: 0
plan: config-setup
state: pending
created-at: '2026-10-31T23:03:59.378738+00:00'
breadth: ''
skill: advanced
created-by: claude
priority: P1
work: S
---

# Declared project identity for shared-gateway authorization

## Description

A shared-gateway server must not authorize from a derived project identity. project_id() falls back to the origin repository NAME (not owner or host), then main-checkout and the directory name, the last two documented as provisional, and its `settings` source reads the fully layered settings, so user or explicit layers can supply it. Add a strict declared-only resolver: the only valid authorization identity is project.id declared in the project's tracked project-scope settings. Derived, user-only and explicit-only values are refused with an actionable error. Reuse the resolver's origin metadata and the existing identity syntax check; no second algorithm. Normal local discovery keeps its fallbacks.

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

Unit tests for each identity case over temporary repositories; architecture and contract suites.

## Effort & Risk



## Standards

docs/design/configuration-model.md (Shared gateway setup); docs/standards/ARCHITECTURE_STANDARDS.md: one identity authority, reuse the existing settings provenance, no second algorithm, evidence-led scope.

## Acceptance Criteria

- Missing, user-only, explicit-only, derived-only, malformed, duplicate and overlapping-root identities each fail with a distinct actionable error
- A valid tracked declaration resolves to the same id in every clone and worktree; client and server resolve the same id
- The reader never follows includes or references (cross-scope injection test)
- Non-gateway callers of project_id() are unchanged
- No new identity algorithm is introduced

## Notes

Prerequisite for CFG15 and CFG16. Independent of CFG14. Design record: docs/design/configuration-model.md, Shared gateway setup. Decided after three GPT review rounds; the keyword-only gateway CLI rejects --options.

Trigger: the shared gateway must not authorize from provisional ids, and CFG15/CFG16 need one id entered once. Prerequisite for CFG15 and CFG16; independent of CFG14. Design record: docs/design/configuration-model.md, Shared gateway setup. Decided after three GPT rounds; then checked against ARCHITECTURE_STANDARDS, ARCHITECTURE_GUIDELINES, SECRETS_MANAGEMENT and CI_RELEASE_GATES (standards review changed placement: foundation, not the project component, because only providers is an approved cross-component API). Deferred variants: repository attestation, per-checkout workspace selectors.

Trigger: the shared gateway must not authorize from provisional ids (origin repository name, main checkout, directory name), and CFG15/CFG16 need one id entered once. Prerequisite for CFG15 and CFG16; independent of CFG14. Design record: docs/design/configuration-model.md, Shared gateway setup. Decided after five GPT rounds and a check against ARCHITECTURE_STANDARDS, ARCHITECTURE_GUIDELINES, SECRETS_MANAGEMENT and CI_RELEASE_GATES (placement is foundation, not the project component, because only providers is an approved cross-component API).

## Change Log

- 2026-10-31T23:03:59.378738+00:00 (created-by): Created by claude
- 2026-10-31T23:04:32.417527+00:00 (updated-by): Updated: section:description, section:steps, section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:06:54.802508+00:00 (updated-by): Updated: section:standards
- 2026-10-31T23:09:43.659951+00:00 (updated-by): Updated: section:steps, section:notes
- 2026-10-31T23:14:25.206806+00:00 (updated-by): Updated: section:steps, section:acceptance_criteria, section:notes
