# Packet Execution Rules

## Each packet must contain
- exact build goal
- dependencies
- files and modules to create/update
- outputs owned by the packet
- explicit non-goals
- step-by-step build instructions
- pseudocode for the core logic
- fixtures to add
- tests to add
- acceptance criteria

## Packet execution rules
- Do not start coding until all dependencies are merged and marked `VERIFIED` in `31_Build_Status_and_Work_Registry.md`.
- If the build registry declares an active structural checkpoint freeze, do not start a newly claimable packet outside that checkpoint unless the registry explicitly exempts it.
- Do not widen packet scope to solve future-phase problems.
- Prefer library code under `src/audiagentic/` and thin CLI wrappers under `tools/`.
- Add fixtures in the same packet that adds the behavior.
- Add tests in the same packet that adds the behavior.
- If a packet discovers a contract issue, stop and raise a contract change request rather than silently diverging.
- Every packet owner must update `31_Build_Status_and_Work_Registry.md` when work is claimed, started, blocked, ready for review, merged, and verified.

## Change control within a packet
- If a file is not listed under packet ownership, treat it as read-only unless a dependency owner approves the edit.
- If a packet needs new shared schema or glossary terms, it must update the contracts packet chain first.

## Additional rules
- Every packet must state whether it uses mock seams or real integrations.
- Any packet that introduces shared errors must use the shared `ErrorEnvelope`.
- Any packet that owns destructive tests must follow `21_Destructive_Test_Sandbox.md`.
- If implementation changes a documented packet behavior, update that packet doc in the same change.
- New packets should include a **Recovery Procedure** section describing cleanup/reset steps after partial failure.

## Build-status discipline
- The build-status registry is authoritative for current work state; do not keep competing packet trackers.
- Before claiming a packet, confirm it is `READY_TO_START` in the registry.
- After merging a packet, update the registry to `MERGED` and then `VERIFIED` once its acceptance criteria and phase evidence are complete.
- Reviews should cite the packet's current registry entry before suggesting new work.
