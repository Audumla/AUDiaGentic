---
id: standard-0007
label: Migration and change-control standard
state: ready
summary: Default standard for documenting migrations, cutovers, compatibility impacts,
  and controlled change rollout.
---

# Standard

Default standard for documenting migrations, compatibility-sensitive changes, cutovers, and controlled rollout in AUDiaGentic-based projects.

# Source Basis

This standard is derived from the repository's migration and lifecycle planning concerns and general change-management practice.

Sources:
- repository migration planning work
- repository lifecycle and install/cutover documentation

# Requirements

1. Any migration or compatibility-sensitive change must document the source state and the target state.
2. Migration planning must identify what remains canonical, what becomes archived, and what is transitional.
3. Changes with compatibility impact must call out:
- affected users or systems
- backward-compatibility expectations
- rollout or sequencing assumptions
- rollback or recovery considerations where relevant
4. Migrations must not silently redefine existing source-of-truth locations without documenting the change.
5. References, links, and entrypoints must be updated as part of the migration scope rather than treated as optional cleanup.
6. Planning records for migrations should define completion in terms of both content movement and reader-facing correctness.
7. If work is only scaffolding for a future migration or installer path, that boundary must be stated explicitly.

# Default Rules

- Prefer explicit source-to-target mapping over vague “migrate remaining items” language.
- Keep cutover assumptions visible.
- Treat stale references and duplicate ownership stories as real migration defects.
- Distinguish design-time scaffolding from active runtime migration logic.

# Non-Goals

- forcing one universal release process for all projects
- replacing project-specific operational runbooks
- requiring rollback plans for trivial low-risk documentation edits
