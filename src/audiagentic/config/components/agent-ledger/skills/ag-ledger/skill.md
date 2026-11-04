---
name: ag-ledger
description: Agent ledger
---

# Agent ledger

Do:
- After substantive implementation work, record a change event with the ag-ledger
MCP tool record_change_event — the ledger is the authoritative release record.
Required fields: change-class, files, technical-summary, user-summary-candidate,
status ('unreleased'). Other fields are auto-generated.
- Each recorded event is its own file under `docs/releases/events/`: commit it with the work it describes. Pass
`plan-item-ids` to link plan items; links are derived (`get_plan_item_events`) and no plan file is edited.
- If a record call fails or its outcome is unknown, retry it: the same event id is idempotent.
- Check release ledger state before changing release notes, changelog fragments, or release workflow files.
- Keep release artifacts and job records synchronized with implementation and review outcomes.
- Do not bypass ledger updates by editing generated release outputs only.

Do not:
- broaden scope beyond the tagged request
