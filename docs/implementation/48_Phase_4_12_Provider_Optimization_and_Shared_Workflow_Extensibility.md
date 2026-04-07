# Phase 4.12 — Provider Optimization and Shared Workflow Extensibility

## Purpose

Phase 4.12 is the next **docs-first optimization slice**.

Its goal is to prepare AUDiaGentic for a lower-token, more script-backed operating style without breaking the current prompt-launch, provider execution, live-stream, or live-input contracts.

This phase is intentionally not a final workflow-model definition. It only defines the extension points needed so a later task/feature tracker or workflow registry can be introduced cleanly.

## What this phase is about

- shared script-backed helpers for large text files
- reusable file scan / find / replace / summarize tooling
- template-driven rendering for repeated docs and reports
- skill-backed or MCP-backed callouts where they reduce token usage
- wrapper-based shortcuts for common operations
- a future-proof seam for a pluggable workflow/task tracker

## What this phase is not about

- it is not a new job engine
- it is not a replacement for the current prompt-launch contract
- it is not a provider-specific execution rewrite, but it may define shared execution-policy config that adapters consume consistently
- it is not a decision on the final tracker schema

## Shared design rule

Prefer deterministic tooling over verbose prompt text when the task is repetitive or mechanical.

Scripts and templates should own the repeatable mechanics.
Agents should only provide the minimal intent, selectors, or parameters needed for the script to do the actual work.

Examples:

- use a script to search/scan a large document instead of asking the model to re-read it in full
- use a patch helper to edit structured text rather than hand-writing a long diff in chat
- use a shared summarizer to produce a compact report from a large file set
- use a template renderer to produce repeatable release or audit documents
- use a skill or MCP tool to standardize provider-facing instructions

## Future extension points

This phase reserves the following seams for later work:

- shared text search helpers
- shared text patch helpers
- shared extraction and summarization helpers
- shared template rendering helpers
- provider instruction/function surface hooks
- provider execution-policy config seams for flags, formats, safety modes, and timeout defaults
- MCP tool hooks
- future workflow/task tracker adapters

## Expected outcome

Once implemented later, the optimization layer should let AUDiaGentic:

- reduce token usage on agent calls
- keep large-file operations script-backed where possible
- keep repeatable content generation template-backed where possible
- avoid duplicating the same helper logic across providers
- introduce a richer workflow model later without forcing a redesign now

## Packetized follow-on work

Phase 4.12 now also owns the shared cross-provider cleanup needed to remove hardcoded execution
policy from adapters. This work is intentionally packetized separately from the active Phase 4.6,
4.9, and 4.11 delivery slices so providers can keep building while shared policy is normalized.

- `PKT-PRV-077` - provider execution policy config contract
- `PKT-PRV-078` - adapter execution flag normalization across providers

`PKT-PRV-077` should define config-driven execution-policy keys in `.audiagentic/providers.yaml`
for provider-specific runtime flags such as output format, permission mode, safety posture,
auto-approval/full-auto behavior, ephemeral mode, target type, and timeout defaults.

`PKT-PRV-078` should refactor adapters to read those settings from config instead of embedding
provider behavior in hardcoded literals where policy belongs in tracked config.

## Current status

- docs-first phase with packetized follow-on work now defined
- implementation remains deferred until the active Phase 4 runtime slices stabilize enough to
  absorb shared policy normalization cleanly
- repeatable operations should remain script-first and template-driven when this phase is
  implemented later

## Next step

Use this phase as the home for later optimization packets, execution-policy normalization, and
future tracker/workflow extensions.
