# Phase 3.3 Prompt Tagged Workflow Shortcuts and Defaults

## Purpose

Document the ergonomic follow-on enhancement to Phase 3.2 that lets users type short action aliases and provider shorthand while still producing the same normalized launch contract and deterministic job creation behavior.

## Current implementation status

The underlying behavior is implemented and verified:
- `@p`, `@i`, `@r`, `@a`, and `@c` resolve to the standard prompt tags
- provider shorthand tokens resolve to provider defaults
- omitted targets create a sensible default runtime subject and job id
- provider-default model selection is loaded during launch/resume

## Why this enhancement exists

The prompt-launch flow was correct but too verbose for common use. This enhancement reduces typing while keeping the launcher deterministic and contract-driven.

## Included work

- parser shorthand aliases
- provider shorthand routing
- default subject generation
- provider config loading and default model resolution
- prompt-launch and integration tests
- build registry and tracker updates

## Not changed

- the core job state machine
- review bundle aggregation
- provider adapter contracts
- release output rules

## Related packet

- `PKT-JOB-010`

## Notes for future work

- If additional shorthand aliases are introduced, they should be added through a new tracked enhancement rather than silently changing the existing `.3` behavior.
