# DRAFT — Provider Optimization and Shared Workflow Extensibility

## Purpose

This draft defines the next optimization slice for AUDiaGentic:

- reduce token usage on repetitive agent calls
- prefer shared scripts or helpers for large-text scan/modify operations
- make repeatable operations script-first and template-driven
- keep agents focused on the minimum intent needed to call those scripts
- allow skills, MCP tools, or wrapper scripts to replace verbose prompt callouts where appropriate
- leave a clean extension seam for a later pluggable workflow/task tracker system

The current contract set remains valid. This draft does **not** replace the existing prompt-launch, provider execution, live-stream, or live-input contracts.

## Scope

This draft is intentionally conservative:

- it does not define the final workflow/task tracker system
- it does not force a single implementation technology
- it does not require every provider to use the same tool path
- it does not deprecate the current prompt-tag or provider bridge contracts

Instead, it defines the extension points that let later implementations swap in:

- shared scripts for large file scanning, patching, and summarization
- provider-specific skills or instruction files
- MCP-backed tools
- wrapper-based shortcuts for common agent tasks

## Shared optimization goals

The optimization layer should prefer deterministic, non-token-heavy operations when possible:

- use scripts instead of long prompt instructions for search/scan/patch tasks
- use templates to standardize repeated document and report generation
- use structured output files instead of lengthy inline summaries
- reuse shared helpers when multiple providers need the same operation
- keep the prompt surface short and delegate repetitive text handling to AUDiaGentic-owned tooling
- have agents supply only the minimal parameters or intent required by the script

## Extension points

The following seams should remain open for later expansion:

- shared file scan helpers
- shared file patch helpers
- shared extraction/summarization helpers
- skill-backed callouts
- MCP tool callouts
- provider-specific wrapper commands
- future workflow/task tracker adapters

## Future workflow model

This draft explicitly leaves room for a later workflow model that may vary by project or be pluggable:

- a task tracker
- a feature tracker
- an issue/work queue
- a job-to-task mapping system
- a pluggable workflow registry

Those systems are intentionally **not defined yet**. The only requirement here is that current contracts do not block them later.

## Provider stance

Providers should be able to participate in the optimization layer using whichever mechanism is most stable:

- direct script invocation
- skills or instruction files
- MCP tools
- wrapper commands

The shared contract should remain the same even if the underlying mechanism differs.

## Operating rule

Repeatable operations should be implemented as code first.

Examples:

- stream capture
- release regeneration
- change-fragment consolidation
- table or ledger updates from known formats
- extract/scan/summarize helpers for large tracked docs

Agents should only be used when the step requires judgment, ambiguity resolution, or intent selection.

## Non-goals

- defining the final tracker schema
- rewriting the current job engine around the future workflow model
- requiring provider-specific duplication of shared tooling
- adding new runtime ownership to the provider

## Outcome

When this phase is implemented later, AUDiaGentic should be able to:

- shorten repetitive prompt callouts
- offload large text handling to scripts/tools
- consolidate repeatable file handling into reusable code instead of agent prompts
- reuse common helpers across providers
- extend into a richer task/work tracking system without breaking the current contracts
