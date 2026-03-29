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
