# Installer v14 pre-import checklist

Use this checklist before any planning-lane import. External only.

## Planning quality

- request, specs, plan, work packages, and tasks still align with current repo standards
- architecture-bearing specs still reference `standard-11`
- work-package split still reflects execution seams
- tasks still include likely surfaces, non-goals, and done criteria
- all tasks have Inputs, Output, Acceptance criteria, and What not to change sections
- all WPs have Acceptance Checks with checkbox items
- all specs have Scope and Constraints sections
- plan has Delivery Approach and Dependencies sections
- request has Notes section

## Import safety

- rerun live id collision check
- confirm import mapping still lands on unused ids
- rewrite all internal refs in one pass using the same mapping
- keep original external pack unchanged for auditability

## Implementation readiness

- no task still depends on hidden policy choices
- packet boundaries still map to likely code/test surfaces
- verification tiers still match current repo test reality
- backward-compatibility boundaries still match current `.audiagentic/*` contracts

## Generic-platform protection

- no spec or task drifted back toward hardcoded canonical-id ownership
- no single current component, overlay, or target is treated as platform center
- target, dependency, overlay, backend, artifact, and realized-capability concepts remain separate

## Stop conditions

Do not import yet if any of these are true:

- live planning ids changed and mapping is stale
- packet scopes became monolithic again
- current-product contracts and installer-platform contracts are blurred
- verification expectations no longer match feasible repo validation
