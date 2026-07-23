# Agent Sessions Complete Replacement Plan Set

This folder is the **complete replacement** for `docs/planning/active/agent-sessions/`.

The replacement has been reconciled against every original active plan (`AS08` through `AS44`). Useful work that was not covered by the rewritten foundation and Pi plans has been carried forward as newly numbered plans `AS47` through `AS58`. Superseded implementation slices and duplicated architecture plans are absorbed into their replacement plans. Git history remains the archive.

## Replacement procedure

1. Create a feature branch.
2. Delete the existing contents of `docs/planning/active/agent-sessions/`, including the old review subfolders.
3. Copy this folder's contents into `docs/planning/active/agent-sessions/`.
4. Run the planning schema/link validation used by the repository.
5. Review the Git diff: the old folder should be replaced by these six control documents and the root-level `AS*.md` plans listed below.
6. Commit the planning replacement separately from implementation work.
7. Give the implementation orchestrator `ORCHESTRATOR.md` as its entry point.

After this replacement, **no old plan file is required alongside this pack**.

## Reading order

1. `ORCHESTRATOR.md`
2. `IMPLEMENTATION.md`
3. `ARCHITECTURE.md`
4. the active `AS*.md` plan file
5. `HARNESSES.md`
6. `DECISIONS.md`

## Plan set

### Foundation

- `AS19` — canonical transport, observation, and evidence contracts
- `AS21` — lifecycle and layered status projection
- `AS29` — resolved session surfaces and generic capability declarations
- `AS30` — durable provider-session bindings
- `AS31` — content/output lane and final-output authority

### Pi baseline and later Pi capabilities

- `AS40` — isolated Pi RPC transport
- `AS41` — Pi lifecycle evidence, state reads, output, and cancellation
- `AS44` — Pi steering and queued follow-up
- `AS45` — compaction, retry, and deep session inspection evidence

### Harness rollout parent

- `AS46` — remaining harness-surface rollout

### Carried-forward original features

- `AS47` — context-bound shared live-session continuation
- `AS48` — bounded redacted metadata event polling
- `AS49` — explicit resume into a new linked generation
- `AS50` — managed model-faithful Codex ACP sessions
- `AS51` — Codex App Server shared gateway/TUI thread
- `AS52` — interactive child-process supervision completion
- `AS53` — proven orphaned-turn recovery
- `AS54` — per-harness observer recipes and validation probes
- `AS55` — OpenCode ACP vertical slice
- `AS56` — SH07 request-status snapshot projection and public integration
- `AS57` — authorized live turn-event and output read surface
- `AS58` — capability-gated external session controls

## Current merge boundary

Complete and merge `AS19`, `AS21`, `AS29`, `AS30`, and `AS31` as **Agent Session Platform Foundation** before beginning Pi RPC or provider vertical-slice work.
