# Phase 4.12 — Provider Optimization and Shared Workflow Extensibility

## Purpose

Phase 4.12 is the next **docs-first optimization slice**.

Its goal is to prepare AUDiaGentic for a lower-token, more script-backed operating style without breaking the current prompt-launch, provider execution, live-stream, or live-input contracts.

This phase is intentionally not a final workflow-model definition. It only defines the extension points needed so a later task/feature tracker or workflow registry can be introduced cleanly.

## What this phase is about

- shared script-backed helpers for large text files
- reusable file scan / find / replace / summarize tooling
- skill-backed or MCP-backed callouts where they reduce token usage
- wrapper-based shortcuts for common operations
- a future-proof seam for a pluggable workflow/task tracker

## What this phase is not about

- it is not a new job engine
- it is not a replacement for the current prompt-launch contract
- it is not a provider-specific execution rewrite
- it is not a decision on the final tracker schema

## Shared design rule

Prefer deterministic tooling over verbose prompt text when the task is repetitive or mechanical.

Examples:

- use a script to search/scan a large document instead of asking the model to re-read it in full
- use a patch helper to edit structured text rather than hand-writing a long diff in chat
- use a shared summarizer to produce a compact report from a large file set
- use a skill or MCP tool to standardize provider-facing instructions

## Future extension points

This phase reserves the following seams for later work:

- shared text search helpers
- shared text patch helpers
- shared extraction and summarization helpers
- provider skill hooks
- MCP tool hooks
- future workflow/task tracker adapters

## Expected outcome

Once implemented later, the optimization layer should let AUDiaGentic:

- reduce token usage on agent calls
- keep large-file operations script-backed where possible
- avoid duplicating the same helper logic across providers
- introduce a richer workflow model later without forcing a redesign now

## Current status

- docs-only draft
- no implementation packet defined yet
- implementation should wait until the optimization tooling surface is agreed

## Next step

Use this draft as the placeholder phase for later optimization packets and future tracker/workflow extensions.
