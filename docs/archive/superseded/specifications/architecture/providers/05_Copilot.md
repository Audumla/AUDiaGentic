# copilot

## Purpose

Optional provider with coding focus and later workflow support.

## Canonical id
- `copilot`

## Install mode
- `external-configured`

## MVP capability expectation
- supports provider descriptor v1
- supports baseline health check
- supports job invocation through provider layer before any optional server work

## Model catalog (Phase 4.1)

Model catalog and selection rules are defined in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`.
Copilot typically uses `access-mode: cli`, with catalog refresh sourced from CLI or API.

## Prompt-tag surface (Phase 4.3)

Prompt-tag recognition and synchronization are defined in `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`.
- CLI surface mode: bridge-wrapper or provider-specific CLI bridge
- VS Code surface mode: extension-normalize
- settings profile: copilot-prompt-tags-v1


## Prompt-trigger exposure (Phase 4.6)

GitHub Copilot exposes tags indirectly through repository instructions, prompt files, and
custom agents. Exact tag parsing belongs in the repository wrapper, which decides which
Copilot prompt file or agent to invoke after the tag has been normalized.

### Chat exposure path
- user types the tagged prompt in Copilot Chat, Copilot CLI, or VS Code agent mode
- the wrapper reads the first non-empty line and resolves the canonical action
- `.github/copilot-instructions.md` and path-scoped instructions state the project doctrine
- `.github/prompts/*.prompt.md` and `.github/agents/*.agent.md` provide the mapped surfaces
- the wrapper forwards the normalized request to the chosen Copilot surface

### Required local assets
- `.github/copilot-instructions.md`
- `.github/prompts/*.prompt.md`
- `.github/agents/*.agent.md`
- optional repo `AGENTS.md` for shared doctrine
- repo-owned wrapper or bridge command

### Fallback path
- if the prompt cannot be routed through the wrapper, exact canonical tag support is not
  guaranteed for that surface
- Copilot-specific behavior stays isolated from the shared grammar docs

## Phase 4.6 implementation runbook

The implementation runbook for Copilot prompt-trigger behavior lives at
`docs/implementation/providers/23_Copilot_Prompt_Trigger_Runbook.md`.

Use that runbook when turning the shared prompt-trigger contract into Copilot-specific
implementation steps, wrapper routing, and smoke tests.

## Current repo state

The repository already contains the Copilot prompt-trigger bridge surface and wrapper:

- `.github/copilot-instructions.md`
- `.github/prompts/*.prompt.md`
- `.github/agents/*.agent.md`
- `tools/copilot_prompt_trigger_bridge.py`

The remaining work for Copilot is therefore operational and validation-oriented rather than
surface discovery.

## Phase 4.9 live stream and progress capture

Copilot is a wrapper-capture provider in the first pass.

Recommended method:
- preserve raw stdout/stderr or wrapper output
- emit bridge-owned milestones rather than depending on a rich native event stream
- keep durable stream persistence owned by AUDiaGentic

## Phase 4.10 live input and interactive session control

Copilot is a record-first provider in the first pass.

Recommended method:
- persist input intent and job/session correlation
- do not claim live session continuation until the provider surface proves it

## Phase 4.11 structured completion and result normalization

Copilot should use instruction files plus wrapper normalization.

Recommended method:
- keep final completion deterministic through repo-owned prompt files or agent files
- normalize wrapper/provider output into the shared result envelope
- avoid depending on interactive-only behavior for the core completion path

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope
