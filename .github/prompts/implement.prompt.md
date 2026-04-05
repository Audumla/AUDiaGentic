---
description: Canonical AUDiaGentic implement prompt
---

# ag-implement prompt

Trigger:
- first non-empty line resolves to `ag-implement` or a configured alias

Do:
- carry out the requested implementation work
- prefer shared helpers and repository-owned scripts
- preserve the tracked-doc and baseline contracts

Do not:
- do not broaden scope beyond the requested change
- do not rewrite contracts without change control

## Bridge invocation

Route tagged prompts through the shared bridge:
  python tools/copilot_prompt_trigger_bridge.py --project-root .

