# Implementation Order and Gates

## Milestone 1 — Agent Session Platform Foundation

Implement in this order:

1. `AS19` — canonical transport, observation, and evidence contracts.
2. `AS21` — lifecycle decisions and layered status projection.
3. `AS29` — sole session-surface/capability declaration and resolution.
4. `AS30` — durable protected bindings and operation gating.
5. `AS31` — separate content lane and final-output authority.

Suggested PR: **Agent Session Platform Foundation**.

### Foundation merge gate

- agents imports no ACP/RPC/provider-native session type;
- one resolved surface and transport are frozen per generation;
- one evidence ingress, lifecycle projector, content owner, final-output selector, surface resolver, and binding owner exist;
- unsupported operations are typed and deterministic;
- no descriptor alone activates a runtime implementation;
- persistence, redaction, crash recovery, and architecture tests pass;
- Pi/provider-specific implementation has not been added to the foundation PR.

## Milestone 2 — Pi RPC baseline

6. `AS40` — isolated Pi native RPC transport and process/runtime lifecycle.
7. `AS41` — Pi RPC lifecycle evidence, state inspection, final output, cancellation, and close.

Use separate PRs unless the transport cannot be reviewed meaningfully without the minimal evidence mapper. The final result must still show distinct commits/slices and independent test evidence.

## Milestone 3 — first external/provider vertical slices

These may proceed after the foundation and their named dependencies:

8. `AS55` — OpenCode ACP vertical slice.
9. `AS47` — context-bound two-client continuation.
10. `AS48` — metadata-only event polling.
11. `AS56` — SH07 status snapshot integration.
12. `AS57` — authorized live event/output reads.
13. `AS58` — external generic controls.

The exact order among 9–13 may change when code dependencies prove a tighter sequence, but `AS48` requires evidence/status contracts, `AS57` requires `AS31`, and `AS58` requires validated internal control handlers.

## Milestone 4 — identity, recovery, and process-hardening features

14. `AS52` — complete interactive child supervision.
15. `AS53` — proven orphaned-turn recovery.
16. `AS49` — explicit resume into a linked generation.

`AS49` depends on real `AS30` binding/context fingerprints and a validated resumable surface. It never reactivates a terminal source record.

## Milestone 5 — Codex surfaces

17. `AS50` — managed model-faithful Codex ACP.
18. `AS51` — shared Codex App Server thread with gateway/TUI.

Treat these as different surfaces and different PRs. `AS51` additionally depends on external ownership/detach semantics and safe concurrent attachment.

## Milestone 6 — observer matrix and later capabilities

19. `AS54` — per-harness observer recipes, probes, and evidence matrix.
20. `AS44` — Pi steering and queued follow-up.
21. `AS45` — compaction, retry, and deep inspection evidence.
22. `AS46` — remaining harness surfaces, one child plan/PR per surface.

`AS54` may begin inventory/probe work earlier, but no runtime declaration is promoted until the foundation contracts and exact surface probe pass.

## PR discipline

- Do not combine unrelated deferred features into a “sessions cleanup” PR.
- Each PR must identify the plans it completes and the plans it only prepares.
- Parent `AS46` is never considered complete because one provider lands; every listed surface must be completed, split into an explicit successor, or explicitly marked unsupported/removed.
- Plans with partially landed baselines must preserve the landed behavior, implement only remaining scope, and delete stale duplicate code rather than replaying old steps blindly.
