<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

# Project instructions

This repository uses AUDiaGentic workflow jobs.

## Prompt tag doctrine

- Parse only the first non-empty line for the workflow tag.
- Keep tag semantics identical to the shared AUDiaGentic launch contract.
- Do not invent provider-specific alternate tags.
- Preserve raw prompt text in provenance metadata.
- Keep provenance visible: provider id, surface, and session id should survive normalization.

<!-- ag:managed:begin -->
_Managed by AUDiaGentic — generated from component configs. Edit the owning component and re-run surface apply; edits here are overwritten._

## Agent ledger process

After substantive implementation work, record a change event with the ag-ledger
MCP tool record_change_event — the ledger is the authoritative release record.
Required fields: change-class, files, technical-summary, user-summary-candidate,
status ('unreleased'). Other fields are auto-generated.
- Check release ledger state before changing release notes, changelog fragments, or release workflow files.
- Keep release artifacts and job records synchronized with implementation and review outcomes.
- Do not bypass ledger updates by editing generated release outputs only.

When recording a change event for work associated with one or more plan items,
include "plan-item-ids" in the event dict (e.g. {"plan-item-ids": ["CC07", "CC08"]}).
The planning component will automatically link the ledger event ID to those items.

## Planning process

Use the ag-planning MCP tools to manage plan items in docs/planning/.

## When to use
- User asks to create a plan or work items 
- Tracking multi-step implementation across sessions
- Reviewing or updating the state of outstanding items

## Item lifecycle
1. Create items with plan_create_item — lands in docs/planning/active/<plan>/
2. Revise content with plan_update_item as work progresses; for a findings-driven correction (not routine progress), record a plan_create_review first, then close it once incorporated
3. After review triage, close handled reviews with plan_set_review_state(review_id, 'closed')
4. Mark done with plan_set_state(item_id, 'completed') only when implementation and validation are done
5. Keep unfinished work pending or in terminal discard states (superseded, deprecated); remove stale items with plan_delete_item

## Item ID convention
Combine a short uppercase plan prefix with a sequence number: CC07, LSP01, ML01.
Choose a prefix matching the plan name (CC → code-cleanup, LSP → lsp-mcp-enhancement).

## Required fields for plan_create_item
- plan: plan directory name (e.g. "code-cleanup")
- title: short descriptive title

## State discipline
- Do not leave incorporated reviews in created/considered; close them.
- Do not mark a parent item completed just because reviews were handled.
- If an active item is superseded, transition to 'superseded' or 'deprecated' rather than deleting (preserves history and linked reviews).

## Optional fields (fill out where applicable to provide complete planning context)
- work: S / M / L — blast radius of the change
- skill: basic / intermediate / advanced — cognitive difficulty
- order: integer sort key (default 0)
- description: Body section describing the work
- steps: Implementation steps
- detailed_solution: Detailed Solution & Technical Design (architecture, components, design)
- code_samples: Code Samples & Guidance (including config samples and schemas)
- files: Files to create/update
- validation: How to validate the implementation
  (include comprehensive tests where possible)
- effort_risk: Complexity and risk assessment
- standards: Applicable standards/rules
- notes: Key design principles and additional context

## Agent profile doctrine

Agent profiles bind a provider to a specific model with optional execution
parameters. They are stored in .audiagentic/config/agent-profiles.yaml.

## When to use
- A job needs a predefined provider+model configuration
- Execution parameters (temperature, max-tokens) should be profile-driven
- Multiple projects need different default model configurations

## Resolution precedence at job launch
1. Explicit `agent-profile-id` in job request
2. Explicit provider-id / model-id in job request
3. Default agent profile (marked `is-default: true`)

## Naming
Use `agent-profile-id` (NOT `profile-id`) in job requests to avoid
collision with `workflow-profile` (lite/standard/strict stage pipelines).

## Memory usage guidance

Use Hindsight memory when prior project context may help.
- Recall before design/history questions or non-trivial work.
- Retain durable decisions, user preferences, architecture constraints, and outcomes.
- Do not retain secrets, credentials, or transient noise.

## Component profile doctrine

Component profiles select an alternative set of component configurations
for a single process invocation. They override the base component
definitions with
per-profile customizations (enabled/disabled components,
overridden mcp-servers,
adjusted parameters).

## What component profiles are

A component profile is a named configuration layer loaded via the
`--component-profile` CLI flag or the `AUDIAGENTIC_COMPONENT_PROFILE`
environment variable. The profile name maps to a project-scoped folder:
`<project-root>/.audiagentic/<profile-name>/components/`. Descriptor
YAML files in that folder layer on top of the base component definitions
from the package's `config/components/`; a profile descriptor sharing an
id with a base descriptor wins (last-wins overlay).

## Distinction from other profile concepts

Three unrelated mechanisms use the word "profile" in this codebase:

- **Component profiles** — select alternative component configurations
  for the harness. Controlled by `--component-profile` /
  `AUDIAGENTIC_COMPONENT_PROFILE`. Stored in
  `<project-root>/.audiagentic/<profile-name>/components/`.

- **Agent profiles** — bind a provider to a specific model with optional
  execution parameters. Used at job-launch time to resolve which model
  invoke. Stored in `.audiagentic/config/agent-profiles.yaml`.
Referenced via
  `agent-profile-id` in job requests.

- **Workflow profiles** — define lite/standard/strict stage pipelines
  task execution. Controlled by `workflow-profile` in job or plan
  configuration. Not the same as component profiles or agent profiles.

Additionally, rig model profiles (controlled by
`AUDIAGENTIC_RIG_MODEL_PROFILE` and related env vars) configure
inference parameters and are orthogonal to all three of the above.

## Usage

- CLI flag: `--component-profile <profile-name>`
- Environment variable: `AUDIAGENTIC_COMPONENT_PROFILE=<profile-name>`
- Default fallback: if neither is set, the harness loads base component
  definitions from `src/audiagentic/config/components/` with no overlay.

## One-profile-per-process constraint

A single process runs with exactly one component profile (or none). The
profile is captured at the first component registration in the process;
requesting a different profile later in the same process raises
VAL-COMP-010. To switch profiles, stop the current session and restart
with a different `--component-profile` value or updated environment
variable.

## Source control doctrine

Do not invoke git or GitHub APIs directly — use the MCP tools.
<!-- ag:managed:end -->
