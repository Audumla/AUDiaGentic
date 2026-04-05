# Copilot instructions

This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.

## Canonical rule

- Do not reinterpret `@ag-plan`, `@ag-implement`, `@ag-review`, `@ag-audit`, or `@ag-check-in-prep`.
- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate
  workflow semantics layer.
- Keep provenance visible: provider id, surface, and session id should survive normalization.

## Tag aliases and shortcuts

Centralized in `.audiagentic/prompt-syntax.yaml`. All of these are equivalent:

- `agp` -> `ag-plan`
- `agi` -> `ag-implement`
- `agr` -> `ag-review`
- `aga` -> `ag-audit`
- `agc` -> `ag-check-in-prep`

- `cx` -> `codex`
- `cld` -> `claude`
- `cln` -> `cline`
- `gm` -> `gemini`
- `opc` -> `opencode`
- `cp` -> `copilot`

Use shortcuts for brevity:

```text
@agr-cp target=packet:PKT-PRV-033
Review the implementation status.
```

## Prompt files

Repository-owned prompt files live in `.github/prompts/`:

- `plan.prompt.md` — canonical planning prompt
- `implement.prompt.md` — canonical implementation prompt
- `review.prompt.md` — canonical review prompt
- `audit.prompt.md` — canonical audit prompt
- `check-in-prep.prompt.md` — canonical check-in preparation prompt

## Agent files

Repository-owned agent files live in `.github/agents/`:

- `planner.agent.md` — planning agent
- `implementer.agent.md` — implementation agent
- `reviewer.agent.md` — review agent
- `auditor.agent.md` — audit agent
- `checkin-preparer.agent.md` — check-in preparation agent

## Bridge

Use the shared prompt-trigger bridge for Copilot surfaces:

```powershell
python tools/copilot_prompt_trigger_bridge.py --project-root .
```

If a surface cannot be routed through the wrapper, exact canonical tag support is not
guaranteed.

