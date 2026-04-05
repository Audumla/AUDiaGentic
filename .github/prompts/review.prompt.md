---
description: Canonical AUDiaGentic review prompt
---

# ag-review prompt

Trigger:
- first non-empty line resolves to `ag-review` or a configured alias

Do:
- perform read-focused validation and completeness review
- identify blockers, missing tests, and contract mismatches
- produce a deterministic review report

Do not:
- do not add implementation work unless explicitly asked
- do not broaden review into feature-scope changes

## Bridge invocation

Route tagged prompts through the shared bridge:
  python tools/copilot_prompt_trigger_bridge.py --project-root .

