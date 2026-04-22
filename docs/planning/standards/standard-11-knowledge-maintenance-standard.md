---
id: standard-11
label: Knowledge maintenance standard
state: ready
summary: Standard for maintaining knowledge pages as current-state documentation with
  event-driven updates
---







# Standard

Standard for how knowledge pages should be written, maintained, and kept current in AUDiaGentic-based projects using event-driven sync.

# Source Basis

This standard is derived from the knowledge component design and event-driven sync architecture, adapted for the repository's knowledge vault model.

Sources:

- [Knowledge Component System Page](../../knowledge/pages/systems/system-knowledge.md)
- [Event-Driven Sync Decision](../../knowledge/pages/decisions/decision-event-driven-sync.md)
- [Event Bridge Pattern](../../knowledge/pages/patterns/pattern-event-bridge.md)
- [Page Lifecycle Pattern](../../knowledge/pages/patterns/pattern-page-lifecycle.md)

# Requirements

1. Knowledge pages are maintained as current-state documentation in the vault (`docs/knowledge/pages/`).
2. All knowledge pages must include YAML frontmatter with required fields:
   - `id` - Unique page identifier
   - `title` - Human-readable title
   - `type` - Page type (system, guide, tool, pattern, decision, glossary, runbook)
   - `status` - Page status (current, deprecated, draft)
   - `summary` - One-line description
   - `owners` - Team or role responsible for maintenance
   - `updated_at` - Last update date (YYYY-MM-DD)
   - `tags` - Keywords for search and filtering
   - `related` - Related page IDs
3. Knowledge pages must document current state, not historical state or implementation plans.
4. Event adapters must be configured to keep knowledge pages synchronized with source artifacts.
5. When planning artifacts change state (done, verified), related knowledge pages are automatically marked stale and sync proposals are generated.
6. Deterministic sync proposals (proposal_mode: deterministic) are automatically applied without manual review.
7. Review-only proposals (proposal_mode: review_only) require manual review before application.
6. Knowledge pages must include sync notes section documenting:
   - When the page should be refreshed
   - What sources trigger updates
   - Sync frequency expectations
7. Stale pages must be reviewed and updated before they mislead agents or users.
8. Incorrect knowledge is treated as worse than missing knowledge.

# Default Rules

- Prefer current-state documentation over historical records.
- Keep knowledge pages aligned with actual repository structure and tool behavior.
- Use event-driven sync to detect when sources change.
- Configure `affects_pages` in event adapters for each knowledge page that documents planning artifacts.
- Use `action: mark_stale` for pages that need review when sources change.
- Use `action: generate_sync_proposal` for pages that need automated update suggestions.
- Use `action: mark_stale_and_generate_sync_proposal` for pages that need both (default for planning events).
- Use `proposal_mode: deterministic` for auto-apply without manual review.
- Use `proposal_mode: review_only` for proposals requiring manual review.
- Configure payload filters to reduce noise (e.g., only trigger on done/verified states).
- Do not claim implementation completeness where only scaffolding or review prep exists.
- Knowledge pages documenting planning artifacts must be linked via event adapter `affects_pages`.

# Event-Driven Maintenance

**When planning tasks complete:**
- Tasks documenting knowledge pages → mark page stale, generate sync proposal
- Tasks implementing features → mark related system/guide pages stale
- Tasks fixing bugs → mark related tool/runbook pages stale

**When work-packages complete:**
- Review related plan or system pages for accuracy
- Mark pages stale if implementation differs from documentation

**When plans complete:**
- Review spec and overview pages
- Update current-state documentation to reflect completed work

**When specs change:**
- Do NOT update current-state knowledge until implementation is done
- Mark related pages as needing review when spec moves to in_progress

# Page Lifecycle

1. **Scaffold**: Create page with required YAML frontmatter and sections
2. **Populate**: Document current state following conventions
3. **Link**: Configure event adapters to track source artifacts
4. **Monitor**: Events mark pages stale when sources change (filtered by payload)
5. **Auto-apply**: Deterministic proposals automatically applied; review-only proposals queued
6. **Maintain**: Keep pages current as sources evolve

# Non-Goals

- Defining planning workflow policy.
- Replacing project-specific architecture decisions.
- Forcing one universal prose style across all documentation surfaces.
- Storing historical records (use planning artifacts for that).
