---
description: Canonical AUDiaGentic check-in prep prompt
---

# ag-check-in-prep prompt

Trigger:
- first non-empty line resolves to `ag-check-in-prep` or a configured alias

Do:
- prepare the repo for a stable check-in
- summarize outstanding changes and verification state
- keep the output concise and action-oriented

Do not:
- do not change implementation behavior
- do not broaden into feature work

## Bridge invocation

Route tagged prompts through the shared bridge:
  python tools/copilot_prompt_trigger_bridge.py --project-root .

