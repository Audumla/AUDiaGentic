# Agent Jobs MVP

## Purpose

Agent jobs are introduced only after release/audit/ledger are working.

## MVP job scope

- execute one packet at a time
- use one selected provider
- write runtime artifacts only
- request approval only when profile requires it
- emit events through the event model

## MVP job state machine

```mermaid
stateDiagram-v2
    [*] --> created
    created --> ready
    ready --> running
    running --> awaiting-approval
    awaiting-approval --> running
    awaiting-approval --> cancelled
    running --> completed
    running --> failed
    ready --> cancelled
```

## Out of scope for MVP

- complex graph workflows
- deep sub-agent delegation
- automatic merge orchestration


## Provider selection for MVP jobs

Provider selection uses the common contract rules:
1. explicit provider on the job request
2. project default provider for the active workflow profile
3. fail validation if no provider is resolved

MVP fallback behavior:
- no automatic failover
- no multi-provider fanout
- if the selected provider health check returns `unhealthy` or `configured: false`, job creation fails before execution begins


## Phase 3.2 extension: prompt-tagged launch and review loop

Phase 3.2 adds a normalized prompt-launch path on top of the existing job engine without changing the base state machine.

Frozen MVP decisions:
- prompt syntax is `prefix-token-v1`
- the first non-empty line must begin with one of the action tags or their short aliases (`@p`, `@i`, `@r`, `@a`, `@c`)
- provider shorthands such as `@codex` or `@claude` are allowed and default the launch path to the provider's standard action and model selection
- shorthand `@adhoc` is allowed and normalizes to `tag=implement` with `target.kind=adhoc`, but may remain feature-gated in the first executable pass
- CLI and VS Code adapters must normalize into `PromptLaunchRequest` before jobs consume the request

Prompt target kinds:
- `packet`
- `job`
- `artifact`
- `adhoc`

Review loop rules:
- review runs against an existing artifact, packet output, or job output
- each review emits a structured `ReviewReport`
- a `ReviewBundle` aggregates multiple reports when policy requires more than one reviewer
- MVP approval policy for multi-review is deterministic `all-pass`
- `@adhoc` may be accepted by the parser/schema even when the feature gate keeps runtime execution disabled
- shorthand provider launches that infer a default runtime subject are treated as default launches, not explicit `@adhoc` requests

Non-goals for Phase 3.2:
- natural-language-only routing
- automatic multi-agent fan-out
- commit execution without approval policy
