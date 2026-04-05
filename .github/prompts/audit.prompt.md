---
description: Canonical AUDiaGentic audit prompt
---

# ag-audit prompt

Trigger:
- first non-empty line resolves to `ag-audit` or a configured alias

Do:
- audit tracked docs, release artifacts, and state consistency
- note drift, missing evidence, or stale references
- avoid implementation work unless explicitly asked

Do not:
- do not mutate tracked docs without approval
- do not hide drift behind vague summaries

## Bridge invocation

Route tagged prompts through the shared bridge:
  python tools/copilot_prompt_trigger_bridge.py --project-root .

