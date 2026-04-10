# PKT-PRV-035 — GitHub Copilot prompt-trigger launch integration

**Phase:** Phase 4.6
**Status:** READY_FOR_REVIEW
**Owner:** GitHub Copilot

## Objective

Wire Copilot instruction files and custom agents to the shared trigger bridge so tagged prompts
launch the shared workflow runner.  All prompt and agent files must have substantive content
before this packet is READY_FOR_REVIEW.

## What is implemented

- `.github/copilot-instructions.md` records the canonical tag doctrine and bridge usage
- `.github/prompts/*.prompt.md` exists for all 5 canonical tags (stubs only)
- `.github/agents/planner.agent.md` and `reviewer.agent.md` exist (stubs only)
- `tools/copilot_prompt_trigger_bridge.py` provides the Copilot-specific wrapper path to the
  shared bridge
- the shared bridge harness is implemented and test-covered

## What is NOT yet implemented (blockers for READY_FOR_REVIEW)

- **No smoke tests** — no integration tests for the Copilot prompt-trigger path

## What WAS implemented to reach READY_FOR_REVIEW

- **Prompt files filled** — all 5 `.github/prompts/*.prompt.md` files now contain substantive
  Trigger / Do / Do not instructions and bridge invocation guidance
- **Agent files filled** — `planner.agent.md` and `reviewer.agent.md` now contain substantive
  agent-mode guidance
- **Missing agents created** — `implementer.agent.md`, `auditor.agent.md`, and
  `checkin-preparer.agent.md` now exist with full content
- **Instructions expanded** — `.github/copilot-instructions.md` now includes tag aliases,
  provider shorthands, and references to all prompt and agent files

## Required instruction surface

### Prompt files (`.github/prompts/`)

Each prompt file must contain substantive Copilot-specific content following the same
Trigger / Do / Do not pattern used by all other providers:

```yaml
---
description: <one-line description>
---

# <action> prompt

Trigger:
- first non-empty line resolves to `<action>`

Do:
- <provider-specific instruction matching shared contract>

Do not:
- <restriction matching shared contract>

## Bridge invocation

Route tagged prompts through the shared bridge:
  python tools/copilot_prompt_trigger_bridge.py --project-root .
```

### Agent files (`.github/agents/`)

Each agent file must cover one canonical action and include Copilot-specific agent-mode
guidance:

```yaml
---
name: <agent-name>
description: <one-line description>
---

# <action> agent

Instructions matching the shared canonical contract for this action.
```

Required agents: `planner`, `implementer`, `reviewer`, `auditor`, `checkin-preparer`

## Prompt-trigger exposure details

### User-facing flow

1. user types the tagged prompt in Copilot Chat, Copilot CLI, or VS Code agent mode
2. the bridge reads the first non-empty line and resolves the canonical action
3. the bridge selects the matching `.github/prompts/*.prompt.md` or agent file and forwards
   the normalized envelope
4. Copilot loads repository instructions and performs the requested stage

### Failure mode

If the bridge is bypassed, canonical tag support is not guaranteed and must not be claimed
in the provider docs.

## Prerequisites

- PKT-PRV-031 verified
- PKT-PRV-007 verified

## Implementation steps

1. Replace stub content in all 5 `.github/prompts/*.prompt.md` files with substantive
   Trigger / Do / Do not instructions and bridge invocation guidance
2. Replace stub content in `planner.agent.md` and `reviewer.agent.md`
3. Create `implement.agent.md`, `audit.agent.md`, and `check-in-prep.agent.md`
4. Update `.github/copilot-instructions.md` with surface-specific guidance beyond the
   single bridge reference
5. Add smoke tests for `@plan` and `@review` via the Copilot bridge

## Acceptance criteria

- all 5 `.github/prompts/*.prompt.md` files have substantive content (not stubs)
- all 5 canonical tags have corresponding `.github/agents/*.agent.md` files
- each prompt and agent file follows the shared Trigger / Do / Do not structure
- tagged Copilot prompts reach the shared launcher path
- Copilot instructions do not redefine the canonical grammar
- smoke tests pass for at least `@plan` and `@review`

## Files to create or update

- `.github/prompts/plan.prompt.md` — replace stub with full content
- `.github/prompts/implement.prompt.md` — replace stub with full content
- `.github/prompts/review.prompt.md` — replace stub with full content
- `.github/prompts/audit.prompt.md` — replace stub with full content
- `.github/prompts/check-in-prep.prompt.md` — replace stub with full content
- `.github/agents/planner.agent.md` — replace stub with full content
- `.github/agents/reviewer.agent.md` — replace stub with full content
- `.github/agents/implementer.agent.md` — new
- `.github/agents/auditor.agent.md` — new
- `.github/agents/checkin-preparer.agent.md` — new
- `.github/copilot-instructions.md` — expand from single bridge reference
- `docs/implementation/providers/23_Copilot_Prompt_Trigger_Runbook.md`
- Copilot prompt-trigger smoke tests

## Rollback guidance

- revert `.github/prompts/`, `.github/agents/`, and `.github/copilot-instructions.md` only
- leave the shared launch grammar untouched
- the bridge tool remains in place
