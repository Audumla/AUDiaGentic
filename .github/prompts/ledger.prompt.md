---
description: Canonical AUDiaGentic ledger prompt
---

# ag-ledger prompt

Trigger:
- first non-empty line resolves to `ag-ledger` or a configured alias

Do:
- inspect ledger state, tracked docs, release artifacts, and project consistency
- note drift, missing evidence, or stale references
- avoid implementation work unless explicitly asked

Do not:
- do not mutate tracked docs without approval
- do not hide drift behind vague summaries

## Bridge invocation

Route tagged prompts through the shared bridge:
  python src/audiagentic/components/optional/prompt_triggers/prompt_trigger_bridge.py --provider-id copilot --project-root .
