---
description: Canonical AUDiaGentic plan prompt
---

# ag-plan prompt

Trigger:
- first non-empty line resolves to `ag-plan` or a configured alias

Do:
- map the requested change into a concrete execution plan
- identify dependencies, blockers, and review checkpoints
- keep the result deterministic and concise

Do not:
- do not implement the requested change
- do not mutate tracked docs without approval

## Bridge invocation

Route tagged prompts through the shared bridge:
  python tools/copilot_prompt_trigger_bridge.py --project-root .

