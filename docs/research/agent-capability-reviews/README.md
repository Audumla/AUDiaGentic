# Agent Capability Reviews

This folder is the tracked review record for delegated agent work. The older
R&D log still exists at `.audiagentic/research/agent-overseer/capability-log.yaml`,
but `.audiagentic/` is local-only/ignored. Use this folder for durable reviews
that should survive across sessions and support later competency analysis.

## Review Rules

- Record one review per delegated request or cohesive local overseer slice.
- Include the gateway request id, profile id, model id, plan item, elapsed time,
  validation performed by the worker, validation repeated by the overseer, and
  any repair the overseer had to apply.
- Score individual competencies from 1 to 5:
  - 1: unsafe, wrong, or high repair burden
  - 2: partial; substantial review or repair needed
  - 3: usable with review; some rough edges
  - 4: strong; minor review or polish
  - 5: excellent; autonomous for this task class
- Keep the written assessment candid. These records are for routing future work,
  not for making every worker look good.

## Competency Vocabulary

- `scope-control`: stayed inside allowed files and task slice.
- `code-correctness`: implemented the intended behavior.
- `test-quality`: wrote meaningful tests rather than lucky or shallow checks.
- `validation-honesty`: accurately reported what passed and what remained.
- `architecture-boundary`: respected ownership and public seams.
- `redaction-hygiene`: avoided leaking prompt/output/tool/session secrets.
- `workflow-discipline`: updated plan/ledger state correctly.
- `reviewability`: produced changes and summary that were easy to inspect.
- `runtime-lifecycle`: handled session/process/gateway lifecycle cleanly.
- `independence`: completed without needing controller repair.

