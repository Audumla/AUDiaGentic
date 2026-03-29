# Discord Overlay V1

## Purpose

Discord is an optional overlay added after the core event and approval model is stable.

## V1 scope

- publish lifecycle summaries
- publish release/job status changes
- publish approval requests
- resolve approvals back into the approval core

## Explicitly deferred

- full session mirroring
- provider-native conversation bridging
- Discord as a required transport

## Dependency rule

Discord depends on core lifecycle, approvals, and events. No core subsystem depends on Discord.
