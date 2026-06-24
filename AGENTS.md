<!-- ag:managed:begin -->
_Managed by AUDiaGentic — generated from component configs. Edit the owning component and re-run surface apply; edits here are overwritten._

## Agent ledger process

After substantive implementation work, record a change event with the ag-ledger
MCP tool record_change_event — the ledger is the authoritative release record.
Required fields: change-class, files, technical-summary, user-summary-candidate,
status ('unreleased'). Other fields are auto-generated.
- Check release ledger state before changing release notes, changelog fragments, or release workflow files.
- Keep release artifacts and job records synchronized with implementation and review outcomes.
- Do not bypass ledger updates by editing generated release outputs only.

## Planning process

Use the ag-planning MCP tools to manage plan items in docs/planning/.

## When to use
- User asks to create a plan or work items for a task
- Tracking multi-step implementation across sessions
- Reviewing or updating the state of outstanding items

## Item lifecycle
1. Create items with plan_create_item — lands in docs/planning/active/<plan>/
2. Revise content with plan_update_item as work progresses
3. Mark done with plan_set_state(item_id, 'completed') — moves to completed/
4. Remove stale or cancelled items with plan_delete_item

## Item ID convention
Combine a short uppercase plan prefix with a sequence number: CC07, LSP01, ML01.
Choose a prefix matching the plan name (CC → code-cleanup, LSP → lsp-mcp-enhancement).

## Required fields for plan_create_item
- id: unique item ID (e.g. "CC20")
- plan: plan directory name (e.g. "code-cleanup")
- title: short descriptive title

## Optional fields
- priority: P0 (critical) / P1 / P2 / P3 / HIGH / MEDIUM (default P2)
- complexity: simple / mid / complex (default simple)
- order: integer sort key (default 0)
- validate_first: true if validation steps must precede implementation (default true)
- description, steps, files, validation, effort_risk, notes: body section content

## Release doctrine

Use the configured release manager for versioning and publication.
Do not edit generated release artifacts (CHANGELOG.md, RELEASE_NOTES.md) directly.
Run finalize_release only after ledger audit review is complete.
The ledger is archived as part of finalization — this cannot be undone.

## Source control doctrine

Do not invoke git or GitHub APIs directly — use the MCP tools.
<!-- ag:managed:end -->
