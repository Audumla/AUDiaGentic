# PKT-PRV-078 — Adapter execution flag normalization across providers

**Phase:** Phase 4.12
**Status:** WAITING_ON_DEPENDENCIES
**Owner:** Infrastructure

## Objective

Refactor provider adapters to consume the shared execution-policy contract so output formats,
permission modes, autonomy flags, target types, and timeout defaults come from config instead of
being hardcoded in adapter command construction.

## Scope

- update Codex, Claude, Cline, Gemini, Qwen, opencode, and Copilot adapters to read
  `providers.<provider-id>.execution-policy`
- remove hardcoded policy values where config should decide behavior
- add tests proving adapters honor configured policy values
- preserve existing behavior through explicit defaults encoded in config rather than hidden in code

## Not in scope

- changing provider business logic beyond policy sourcing
- shared streaming hardening under Phase 4.9.1
- structured-completion parsing behavior beyond config-driven execution mode selection

## Files likely to change

- `src/audiagentic/execution/providers/adapters/codex.py`
- `src/audiagentic/execution/providers/adapters/claude.py`
- `src/audiagentic/execution/providers/adapters/cline.py`
- `src/audiagentic/execution/providers/adapters/gemini.py`
- `src/audiagentic/execution/providers/adapters/qwen.py`
- `src/audiagentic/execution/providers/adapters/opencode.py`
- `src/audiagentic/execution/providers/adapters/copilot.py`
- adapter tests

## Dependencies

This packet should start after `PKT-PRV-077` freezes the config contract and after the active
Phase 4 runtime slices are stable enough that cross-provider adapter refactoring will not create
avoidable churn.

## Acceptance criteria

- adapter command construction no longer embeds policy-bearing literals when config owns them
- provider tests prove configured execution-policy values flow into command construction
- safety-sensitive modes remain explicit in config and are not silently enabled by code defaults
- adapter behavior remains deterministic when policy keys are omitted
