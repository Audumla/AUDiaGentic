---
id: standard-7
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

- Repository migration planning work
- Repository lifecycle and install/cutover documentation
- [Expand-Contract (Parallel Change) pattern](https://martinfowler.com/bliki/ParallelChange.html) — safe migration sequencing
- [Google SRE — Managing Change](https://sre.google/sre-book/managing-change/) — controlled rollout and rollback

# Requirements

1. Any migration or compatibility-sensitive change must document the source state and the target state before work begins.
2. Migration planning must identify what remains canonical, what becomes archived, and what is transitional for the duration of the migration.
3. Changes with compatibility impact must call out:

   - affected users, systems, or components
   - backward-compatibility expectations
   - rollout or sequencing assumptions
   - rollback or recovery considerations where relevant

4. Migrations must not silently redefine existing source-of-truth locations without documenting the change.
5. References, links, and entrypoints must be updated as part of the migration scope rather than treated as optional cleanup.
6. Planning records for migrations must define completion in terms of both content movement and reader-facing correctness — not just code change.
7. If work is only scaffolding for a future migration or installer path, that boundary must be stated explicitly. Scaffolding must not be marked as completed migration.
8. Migrations that change configuration schema must provide a migration path per standard-0011 (config-driven design): document old and new schema, provide defaults or transformation guidance, and state what happens if the old config is left in place.
9. Migrations that change module or extension point contracts must follow the extensibility requirements in standard-0011: treat interface removal or signature change as breaking, and sequence expand-then-contract where possible.
10. Hook or event subscription migrations must keep the old mechanism operational in parallel until all consumers have migrated, with a defined removal condition.

# Default Rules

- Prefer explicit source-to-target mapping over vague "migrate remaining items" language.
- Keep cutover assumptions visible and dated where possible.
- Treat stale references and duplicate ownership stories as real migration defects.
- Distinguish design-time scaffolding from active runtime migration logic.
- Use expand-contract sequencing: add the new thing, migrate consumers, then remove the old thing.

# Non-Goals

- Forcing one universal release process for all projects.
- Replacing project-specific operational runbooks.
- Requiring rollback plans for trivial low-risk documentation edits.
