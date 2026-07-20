# 2026-07-19 SH07 C1 Queue Context Substitution — deep-coder-opencode

- Request: `req_b2fc1d84281045c2` (first attempt `req_c225d5d59b464d40` failed on
  harness infrastructure, see the 2026-07-19 batch incident doc)
- Agent profile: `deep-coder-opencode`
- Model: `brutus/coder-quality-mid`
- Plan item: SH07, repair C1 (Critical)
- Task class: single-file concurrency correctness fix with immutable dispatch entries
- Turn time: ~7.5 minutes
- Outcome: accepted with no controller code repair required

## Task shape

The handoff provided the full solution design: an immutable `QueuedDispatch`
dataclass, exact fields, which dicts to delete, the new `_drain(pq)` signature,
cancel/slot-status scan semantics, a named isolation test, forbidden files, and
the exact validation command. The worker's job was faithful mechanical
execution plus test synthesis.

## Competency scores

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 5 | Touched exactly the two allowed files; no forbidden APIs. |
| code-correctness | 5 | Entry-based dispatch is faithful to the design; lock ordering, AS15 idle logic, and event choke points preserved; the lost-owner branch correctly disappeared. |
| test-quality | 4 | `test_sh07_per_request_dispatch_isolation` (distinct roots + runners) and the two-entry cancel test assert the right invariants; entry removal loop is O(n) scan as specified. |
| validation-honesty | 5 | Reported 84 passed; controller rerun reproduced 84 passed exactly. |
| architecture-boundary | 5 | No store/recovery/api edits; service_root threading matched the pre-existing claim_dispatch contract. |
| redaction-hygiene | 4 | No diagnostics surface changes; params frozen via MappingProxyType as instructed. |
| workflow-discipline | 5 | Recorded ledger `chg_20260719_074734_fixed-gateway-queue-bug-where_7392`; did not touch plan state; stopped after fix + validation. |
| reviewability | 5 | Final summary matched the diff exactly (2 files, 2 new tests, counts). |
| runtime-lifecycle | 4 | Turn completed cleanly end_turn; session closed by controller after review. |
| independence | 5 | Zero controller repair needed on this lane. |

## Controller review

- Diff inspected line by line against the design: all seven design points
  implemented as specified, including the subtle requirement that `_drain`
  consumes only entry-carried context and that enqueue's event publishes remain
  outside `pq.lock`.
- Controller rerun of the validation suite: 84 passed in 9s. Combined
  batch-level gateway slice after all lanes merged: 186 passed.

## Assessment

Best deep-coder result to date. The difference from earlier AS33/AS34 runs is
handoff altitude: when the controller supplies the complete design (dataclass
shape, signatures, deletion list, named tests), this profile executes a
Critical concurrency fix without churn. Keep using deep-coder for
mechanically-specified single-file correctness work; keep design synthesis with
the controller.
