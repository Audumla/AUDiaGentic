# 2026-07-19 AS Gateway Worker Reviews

These reviews cover the first production-style gateway delegation batch for AS
items. Three OpenCode profiles ran in parallel through `ag-agents-gateway`; the
overseer then reviewed outputs, cleaned rough edges, reran focused validation,
updated plan state, and closed sessions.

## Batch Summary

| Request | Profile | Plan | Slice | Result | Overall |
| --- | --- | --- | --- | --- | --- |
| `req_29f1b762e18a4c36` | `lite-coder-opencode` | AS11 | Research hygiene | Completed | 4/5 |
| `req_6fcce83c451442f0` | `supp-coder-opencode` | AS16 | Snapshot/race tests | Completed | 3/5 |
| `req_979fd124e1814376` | `deep-coder-opencode` | AS16 | Public diagnostics stack | Completed | 4/5 |
| local overseer | `codex` | AS26 | Corrective slice | Completed slice only | 4/5 |

Gateway lifecycle result: all three worker requests completed, all three live
sessions were explicitly closed, and final gateway overview showed no running
requests or live sessions.

## Review: AS11 Research Hygiene

- Request: `req_29f1b762e18a4c36`
- Agent profile: `lite-coder-opencode`
- Model: `brutus/coder-quality-lite`
- Plan item: AS11
- Task class: R&D artifact hygiene, redaction, public client seam, focused tests
- Outcome: accepted after small overseer polish

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 5 | Stayed in AS11 research/test scope; did not alter production gateway code. |
| code-correctness | 4 | Correctly switched helper to `get_gateway_client()` and added redaction helper. |
| test-quality | 3 | Useful fake client/redaction tests, but used `any` instead of `Any` and tested some in-memory fake behavior rather than the helper path directly. |
| validation-honesty | 4 | Reported focused tests and remaining prompt-template caveats clearly. |
| architecture-boundary | 5 | Moved off internal gateway API to public client seam. |
| redaction-hygiene | 4 | Redacted main helper output and capability log; overseer further changed `traceback` to `traceback-redacted` and cleaned one local run summary. |
| workflow-discipline | 4 | Recorded ledger `chg_20260719_015728_closeout-hygiene-for-overseer_9316`; did not mark AS11 complete prematurely. |
| reviewability | 4 | Summary listed files, validation, and remaining gaps cleanly. |
| runtime-lifecycle | 4 | Gateway turn completed cleanly; session closed by overseer. |
| independence | 4 | Needed only small polish, not a behavioral repair. |

Controller repair or polish:

- Replaced test type hints using builtin `any` with `typing.Any`.
- Changed helper failure payload from `traceback: "[REDACTED]"` to `traceback-redacted: true`.
- Redacted historical ACP session ids in the local capability log.
- Cleaned the local CC41 run summary to use boolean redaction markers instead of keeping `prompt-body`/`output` keys.

Assessment:

Good fit for bounded hygiene, redaction, and public-seam cleanup. Continue to
use lite worker for low-risk artifact/test hygiene where the desired file scope
is explicit and overseer validation is cheap.

## Review: AS16 Snapshot And Race Tests

- Request: `req_6fcce83c451442f0`
- Agent profile: `supp-coder-opencode`
- Model: `brutus/coder-quality-suppliment`
- Plan item: AS16
- Task class: immutable queue/session diagnostics snapshots and race tests
- Outcome: accepted after overseer test cleanup

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 4 | Stayed broadly in queue/session tests and snapshot support. |
| code-correctness | 4 | Added useful `_snapshot_all()` and `session_snapshot_all()` primitives. |
| test-quality | 2 | Initial tests passed but included duplicate sections, weak assertions such as `assert "pA" in snap or True`, and local fake transport duplication. |
| validation-honesty | 3 | Reported passing suites, but did not flag that several tests were shallow/rough. |
| architecture-boundary | 4 | Did not cross provider boundaries or add persistence. |
| redaction-hygiene | 4 | Diagnostics stayed metadata-only. |
| workflow-discipline | 4 | Recorded ledger `chg_20260719_015625_added-immutable-snapshot-metho_3894`; did not mark AS16 complete. |
| reviewability | 3 | Summary was clear, but diff required cleanup before it was a good template. |
| runtime-lifecycle | 3 | Session snapshot test initially swallowed close-time exceptions; overseer moved coverage into established session tests. |
| independence | 3 | Useful implementation, but needed meaningful overseer cleanup. |

Controller repair or polish:

- Removed weak/duplicated snapshot tests from `test_agents_gateway_queue.py`.
- Kept queue invariant tests that actually assert useful state.
- Moved session snapshot coverage into `test_agents_gateway_sessions.py`, reusing existing fixture/fake transport.
- Reran `tests/unit/agents/test_agents_gateway_queue.py tests/unit/agents/test_agents_gateway_sessions.py -q` -> 55 passed.

Assessment:

Good for bounded pattern-following and mechanical support code, but test quality
needs review. Do not hand this profile broad "prove race correctness" work
without asking for exact invariants and expecting controller cleanup.

## Review: AS16 Public Diagnostics Stack

- Request: `req_979fd124e1814376`
- Agent profile: `deep-coder-opencode`
- Model: `brutus/coder-quality-mid`
- Plan item: AS16
- Task class: public API/client/service/MCP exposure and integration tests
- Outcome: accepted after one small type/value correction

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 4 | Stayed in AS16 public gateway stack, though touched active-work service-root plumbing from nearby dirty tree. |
| code-correctness | 4 | Correctly exposed `request_runtime_status` through client, application, remote client, service invocation, and MCP. |
| test-quality | 4 | Added useful public stack/E2E coverage; overseer validation passed. |
| validation-honesty | 4 | Reported broad agent unit and E2E validation with counts. |
| architecture-boundary | 5 | Used public gateway seams; no provider leakage. |
| redaction-hygiene | 4 | Diagnostics stayed redacted/metadata-only. |
| workflow-discipline | 4 | Recorded ledger `chg_20260719_015842_request-runtime-diagnostics-no_4200`; left AS16 for overseer closeout. |
| reviewability | 4 | Summary matched diff and remaining gaps. |
| runtime-lifecycle | 4 | Gateway turn completed cleanly; session closed by overseer. |
| independence | 4 | Needed only a small correction. |

Controller repair or polish:

- Changed `_dispatch_service_root` passed by `GatewayServiceApplication` from
  string to `Path` to match the API/queue/store contract.
- Updated the service application unit expectation.
- Reran public stack/E2E validation:
  `tests/unit/agents/test_agents_gateway_client.py tests/unit/agents/test_gateway_remote_client.py tests/unit/agents/test_gateway_service_application.py tests/integration/agents/test_gateway_e2e_states.py -q` -> 23 passed.

Assessment:

Best fit of this batch for vertical-slice public API work when the desired stack
is enumerated. Good candidate for future mid-complexity gateway/client plumbing
with controller review.

## Review: AS26 Local Overseer Corrective Slice

- Request: local overseer work, not delegated
- Agent/profile: Codex session
- Plan item: AS26
- Task class: semantic correction and recovery-authority cleanup
- Outcome: accepted slice; AS26 remains active for proven-dead/closing-state work

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 4 | Limited to AS26 corrective RV721 slice; did not close AS26. |
| code-correctness | 4 | Removed duplicate API recovery authority and relabelled silence timeout semantics. |
| test-quality | 4 | Added guard against `reconcile_gateway_state`; updated session test and schema. |
| validation-honesty | 5 | Reported AS26 remains active for larger proven-dead work. |
| architecture-boundary | 5 | Preserved SH07 recovery as single durable request authority. |
| redaction-hygiene | 4 | No content-bearing diagnostics added. |
| workflow-discipline | 4 | Recorded ledger `chg_20260719_020830_removed-a-duplicate-gateway-re_4167`; updated AS26 notes. |
| reviewability | 4 | Small, focused diff with targeted grep checks. |
| runtime-lifecycle | 4 | Clarified policy timeout vs orphan/death evidence. |
| independence | 4 | Completed without extra worker handoff. |

Validation:

- `tests/unit/agents/test_agents_gateway_sessions.py tests/unit/agents/test_agents_gateway_recovery.py -q` -> 36 passed.

Assessment:

Keep this kind of ownership/semantics correction local until plans are split
into exact mechanical work. Once the AS17 process evidence seam is settled,
subtasks under AS26 can be delegated more safely.

## Initial Routing Takeaways

- `deep-coder-opencode`: best current candidate for end-to-end gateway/client
  slices with clear public stack instructions.
- `supp-coder-opencode`: useful for bounded mechanical additions, but test
  rigor needs explicit invariant requirements and controller review.
- `lite-coder-opencode`: useful for research/doc/test hygiene and bounded
  low-risk cleanup.
- All profiles need independent validation before plan state changes.
- Plan handoff quality matters: code-level file scope, validation commands,
  forbidden files, and plan-state rules materially improved outcomes.

## Batch 2 Summary: AS33 Capability Projection

| Request | Profile | Plan | Slice | Result | Overall |
| --- | --- | --- | --- | --- | --- |
| `req_ad827a310e8d430f` | `deep-coder-opencode` | AS33 | Capability projection implementation | Completed | 4/5 |
| `req_d420c8d9e82e4bb5` | `lite-coder-opencode` | AS33 | Diagnostics test/review | Completed | 3/5 |
| `req_17cc8cf079704c2e` | `supp-coder-opencode` | AS33 | Static contract guards | Completed | 4/5 |
| `req_611a248fcc774a52` | `deep-coder-opencode` reused session | AS33 | Controller repair review | Completed | 4/5 |

Controller validation after review/repair:

- `tests/unit/agents/test_as33_capabilities_contract.py tests/unit/agents/test_agents_gateway_session_bindings.py tests/integration/agents/test_gateway_e2e_states.py -q` -> 26 passed.
- `tests/unit/agents/test_as33_capabilities_contract.py tests/unit/agents/test_agents_gateway_session_bindings.py tests/integration/agents/test_gateway_e2e_states.py tests/unit/agents/test_agents_event_topics.py tests/unit/foundation/event/test_event_topic_conformance.py -q` -> 41 passed.

Harness cleanup validation:

- Reusing `ses_a5023cf5bd0444b1` for `req_611a248fcc774a52` was materially faster than the cold AS33 implementation turn and preserved context well.
- After all AS33 turns completed, controller explicitly closed `ses_c42f438741a047b0`, `ses_599cc8c701534b3f`, and `ses_a5023cf5bd0444b1`.
- Gateway overview after close reported seven completed requests, zero queued/running requests, and `active-count: 0` live sessions.
- `agent_llm_session_list(state="active")` still reported two older non-live persisted sessions from 2026-07-17. That is not a live harness leak from this batch, but it is stale active-record hygiene to plan separately.
- `agent_llm_session_close` returns richer protected binding details than overview/list. Do not paste those raw close results into review artifacts; the close tool output surface should get redaction review.

## Review: AS33 Capability Projection Implementation

- Request: `req_ad827a310e8d430f`
- Agent profile: `deep-coder-opencode`
- Model: `brutus/coder-quality-mid`
- Plan item: AS33
- Task class: public diagnostics projection enabling slice
- Outcome: accepted after controller repair

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 4 | Stayed in AS33 diagnostics/projection files. Temporary restore-to-HEAD during merge repair requires careful controller review in dirty trees. |
| code-correctness | 4 | Correctly added explicit-snapshot-only projection and diagnostics wiring. |
| test-quality | 4 | Added useful absent, explicit snapshot, redaction, and no-runtime-start integration tests. |
| validation-honesty | 4 | Reported focused passing tests and called out unrelated broader failures. |
| architecture-boundary | 4 | Did not implement AS19/AS29 or infer from provider behavior. |
| redaction-hygiene | 3 | Top-level unsafe keys were dropped; controller added nested unsafe-key redaction. |
| workflow-discipline | 4 | Recorded ledger `chg_20260719_022650_session-diagnostics-can-now-op_4936`; did not mark AS33 complete. |
| reviewability | 3 | Summary was clear, but overlapping edits caused corruption/repair churn during the turn. |
| runtime-lifecycle | 3 | Initial ordering read capabilities after runtime status; controller moved raw read before possible schema-aware rewrite. |
| independence | 3 | Delivered the main slice but needed controller fixes for nested redaction and read ordering. |

Controller repair or polish:

- Dropped forbidden capability keys at any nested depth inside whitelisted fields.
- Read raw captured capabilities before live runtime status can rewrite schema-known session records and lose future snapshot fields.
- Cleaned non-ASCII separators introduced in new code/tests.

Assessment:

Good fit for designed vertical slices when file scope and constraints are explicit.
Still needs controller review in dirty trees because repair actions can become broad
when overlapping workers edit the same file.
Future prompts should explicitly include adversarial nested redaction cases and
state why capability reads must happen before schema-aware runtime/status writes.

## Review: AS33 Diagnostics Test/Review

- Request: `req_d420c8d9e82e4bb5`
- Agent profile: `lite-coder-opencode`
- Model: `brutus/coder-quality-lite`
- Plan item: AS33
- Task class: validation/test-review
- Outcome: useful but mostly overlapped with deep implementation

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 4 | Stayed in AS33 test/review scope. |
| code-correctness | 3 | Helped repair overlapping test state but mostly converged on the existing implementation. |
| test-quality | 3 | Confirmed focused AS33 integration behavior; did not add the nested redaction gap. |
| validation-honesty | 4 | Reported schema caveat and no-inference behavior clearly. |
| architecture-boundary | 4 | Did not infer capabilities or broaden AS33. |
| redaction-hygiene | 3 | Covered top-level redaction; missed nested unsafe values. |
| workflow-discipline | 4 | Did not mark AS33 complete. |
| reviewability | 3 | Output described the overlap but contained noisy merge-conflict repair narrative. |
| runtime-lifecycle | 3 | Identified schema/raw-read caveat but did not catch the runtime-status rewrite ordering. |
| independence | 3 | Useful validation, limited independent value because implementation was already present. |

Assessment:

Useful as a low-cost confirmation pass, especially on schema/test caveats. For
parallel validation, give this profile a non-overlapping test seam or require a
specific missing invariant so it does not spend most of the turn reconciling
another worker's edits.

## Review: AS33 Static Contract Guards

- Request: `req_17cc8cf079704c2e`
- Agent profile: `supp-coder-opencode`
- Model: `brutus/coder-quality-suppliment`
- Plan item: AS33
- Task class: unit/static contract guard
- Outcome: accepted after controller repair

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 4 | Stayed in projection helper/tests. |
| code-correctness | 4 | Added broad helper contract coverage and converged on the same helper shape. |
| test-quality | 4 | Unit contract tests covered no snapshot, whitelist, forbidden top-level keys, no inference, and scalar filtering. |
| validation-honesty | 4 | Reported passing focused tests and schema caveat. |
| architecture-boundary | 4 | Did not implement AS29/AS19 or provider inference. |
| redaction-hygiene | 3 | Top-level guard was good; nested unsafe-key leak still needed controller test/fix. |
| workflow-discipline | 4 | Did not mark AS33 complete. |
| reviewability | 4 | Contract file was easy to inspect. |
| runtime-lifecycle | 3 | Did not catch diagnostics read-order issue. |
| independence | 4 | Delivered useful reusable tests with minor controller repair. |

Assessment:

Better than the first supp slice for bounded contract testing. Strong candidate
for future "write focused guards for this exact helper/contract" handoffs, as
long as nested/adversarial cases are spelled out.

## Review: AS33 Reused-Session Controller Repair Review

- Request: `req_611a248fcc774a52`
- Agent profile: `deep-coder-opencode`
- Model: `brutus/coder-quality-mid`
- Session reused: `ses_a5023cf5bd0444b1`
- Plan item: AS33
- Task class: review-only validation of controller repairs
- Outcome: accepted

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 5 | Stayed review-only and did not edit files. |
| code-correctness | 4 | Correctly confirmed nested redaction and read-order repairs. |
| test-quality | 4 | Ran focused tests and tied findings to named tests. |
| validation-honesty | 4 | Reported observations separately from blocking bugs. |
| architecture-boundary | 4 | Kept AS33 as enabling slice and did not propose AS19/AS29 implementation. |
| redaction-hygiene | 4 | Confirmed key-level nested redaction; noted value-string false positive caveat in tests. |
| workflow-discipline | 4 | Did not mark AS33 complete. |
| reviewability | 5 | Concise findings with useful non-blocking observations. |
| runtime-lifecycle | 4 | Confirmed raw read before runtime status rewrite; flagged a separate `list_llm_sessions` side-effect concern. |
| independence | 4 | Produced useful review without controller repair. |

Assessment:

Reusing the same deep session for a related review was effective and faster than
the cold-start implementation turn. This is a good template for follow-up
review/fix loops: keep the same session alive for the same plan item, provide
the exact controller repairs to inspect, and ask for findings rather than broad
implementation.

## Prompting Lessons From AS33

- Include exact adversarial examples in the handoff, not only the policy. For
  redaction work, say "include forbidden keys nested inside whitelisted dicts"
  and "do not only test top-level keys."
- Explain lifecycle ordering when it matters. In AS33, "read raw snapshot before
  `runtime.session_runtime_status()` because schema-aware runtime status may
  rewrite and drop future fields" would likely have avoided a controller repair.
- Split parallel workers onto non-overlapping seams. Three workers editing the
  same helper/test file caused merge churn; future batches should assign one
  implementation worker, one unit-contract worker, and one integration/client
  worker with explicit files or review-only scope.
- For harness lifecycle tests, record both queue/request state and session live
  state, then explicitly close keep-alive sessions after review. Treat stale
  non-live active records as separate recovery hygiene, not as a live leak.

## Batch 3 Summary: AS34 Stale Session Listing

| Request | Profile | Plan | Slice | Result | Overall |
| --- | --- | --- | --- | --- | --- |
| `req_91cd09dde7504853` | `deep-coder-opencode` | AS34 | Session listing implementation | Completed | 3/5 |
| `req_375f80a47ab84f30` | `lite-coder-opencode` | AS34 | Test-only stale session coverage | Completed | 4/5 |
| `req_1c08f1e977a3435f` | `supp-coder-opencode` | AS34 | Review/static contract | Completed | 3/5 |

Controller validation after review/repair:

- `tests/unit/agents/test_agents_gateway_sessions.py tests/unit/agents/test_agents_gateway_recovery.py -q` -> 40 passed.
- `tests/unit/agents/test_agents_gateway_sessions.py tests/unit/agents/test_agents_gateway_recovery.py tests/integration/agents/test_gateway_e2e_states.py -q` -> 50 passed.

Harness cleanup validation:

- AS34 opened three keep-alive sessions: deep, lite, and supp.
- After all requests completed, controller explicitly closed all three sessions.
- Gateway overview after close reported ten completed requests, zero queued/running requests, and `active-count: 0` live sessions.
- The raw `agent_llm_session_close` tool result again exposed protected binding internals to the controller surface. This was not copied into durable review text, but it reinforces the need for a redacted close-result follow-up.

## Review: AS34 Session Listing Implementation

- Request: `req_91cd09dde7504853`
- Agent profile: `deep-coder-opencode`
- Model: `brutus/coder-quality-mid`
- Plan item: AS34
- Task class: read-only session listing implementation
- Outcome: accepted after controller cleanup

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 3 | Stayed in session API/tests but also left duplicate AS34 tests and worked around churn. |
| code-correctness | 4 | Correctly changed listing to use `peek_session_runtime()` and added stale non-live diagnostics. |
| test-quality | 3 | Tests were useful but duplicated and field naming changed during the turn. |
| validation-honesty | 3 | Reported 35 passing tests, but the controller had to rerun a broader suite and remove a reintroduced recovery authority. |
| architecture-boundary | 3 | Core AS34 boundary was right; dirty tree still contained the forbidden public recovery sweep. |
| redaction-hygiene | 4 | Public listing stayed redacted; close-tool raw output remains a separate surface concern. |
| workflow-discipline | 4 | Recorded ledger `chg_20260719_024602_session-listing-no-longer-star_1739`; did not mark AS34 complete. |
| reviewability | 3 | Summary was useful but contradicted final controller-chosen field name during churn. |
| runtime-lifecycle | 4 | Fixed the read-only runtime creation side effect. |
| independence | 3 | Main implementation was good; controller needed dedupe and AS26 regression cleanup. |

Controller repair or polish:

- Kept one canonical diagnostic shape: `runtime-state: "stale-non-live"`.
- Removed duplicate AS34 tests and retained the stronger stale persisted active-row cases.
- Removed the reintroduced `agents_gateway_api.reconcile_gateway_state` second recovery authority so the AS26 guard passes again.

Assessment:

Good implementation candidate when the prompt names forbidden calls directly.
Future handoffs should explicitly say: "Do not add or restore
`reconcile_gateway_state`; `tests/unit/agents/test_agents_gateway_recovery.py`
must pass." This needs to be in the plan template for any recovery-adjacent work.

## Review: AS34 Test-Only Coverage

- Request: `req_375f80a47ab84f30`
- Agent profile: `lite-coder-opencode`
- Model: `brutus/coder-quality-lite`
- Plan item: AS34
- Task class: test-only validation
- Outcome: accepted with useful prompt/template lessons

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 5 | Stayed test-only as requested. |
| code-correctness | 4 | Correctly identified implementation expectations and fixed tests to match valid session records. |
| test-quality | 4 | Added/cleaned meaningful stale-row, live-row, and no-runtime-start coverage. |
| validation-honesty | 4 | Reported failures during iteration and final passing state. |
| architecture-boundary | 4 | Did not create a recovery authority or mutate session state. |
| redaction-hygiene | 4 | Included provider-ref leakage checks. |
| workflow-discipline | 4 | Did not mark AS34 complete. |
| reviewability | 4 | Clear summary of changed tests and why raw handcrafted records were wrong. |
| runtime-lifecycle | 4 | Focused on no side-effect runtime creation. |
| independence | 4 | Useful validation with limited controller repair. |

Assessment:

This was a good use of the lite profile: constrained test-only work with explicit
requirements. It also surfaced a plan-template lesson: require test fixtures to
use store builders instead of hand-crafted records when schemas are strict.

## Review: AS34 Review/Contract Slice

- Request: `req_1c08f1e977a3435f`
- Agent profile: `supp-coder-opencode`
- Model: `brutus/coder-quality-suppliment`
- Plan item: AS34
- Task class: review/static contract
- Outcome: accepted after controller cleanup

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 3 | Review prompt asked for mostly review/test, but the worker edited implementation/tests amid churn. |
| code-correctness | 3 | Correctly identified peek-vs-get issue and redaction state, but field naming churn persisted. |
| test-quality | 3 | Helped get tests green but duplicated/overlapped with deep/lite work. |
| validation-honesty | 4 | Reported architectural findings and plan-specific lessons clearly. |
| architecture-boundary | 4 | Called out read-only runtime side effects and avoided provider signalling. |
| redaction-hygiene | 4 | Confirmed public binding projection redaction. |
| workflow-discipline | 3 | Did not mark complete; ledger event attempt/status was less clear than deep's. |
| reviewability | 3 | Useful findings, but hard to separate from overlapping edits. |
| runtime-lifecycle | 4 | Focused on no runtime creation in listing. |
| independence | 3 | Helpful but needed controller consolidation. |

Assessment:

Useful for review checklists, but overlapping edit permissions reduced signal.
Future "review/static" prompts should say "do not edit implementation; create a
review note or one static test only" when another worker owns the implementation.

## Prompting Lessons From AS34

- Name forbidden APIs directly in plan items and prompts. For this slice:
  `get_session_runtime()` was forbidden in read-only listing, and
  `reconcile_gateway_state` was forbidden entirely.
- Specify exact public field names before parallel work starts. AS34 churned
  between `stale-live-state` and `runtime-state`; the controller chose
  `runtime-state: "stale-non-live"` as the canonical diagnostic.
- Tell agents to use store builders for synthetic records. Hand-crafted v2
  session records drifted from strict binding schema.
- For concurrent agents, assign one editor per file or make later workers
  review-only. Three workers touching the same test file produced avoidable
  duplicate tests.

## Review: AS35 Close-Redaction With Self-Review Prompt

- Request: `req_4a8a1dd00e684e9e`
- Agent profile: `deep-coder-opencode`
- Plan item: AS35
- Task class: implementation with requested self-review
- Outcome: accepted after controller repair; self-review experiment inconclusive

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 4 | Stayed on the close-result redaction slice. |
| code-correctness | 4 | Added a shared public session projection and used it for list/close paths. |
| test-quality | 3 | Covered live, durable, idempotent, and stale close paths, but missed full-key assertions on two paths. |
| validation-honesty | 2 | The request never returned final output, so no worker validation or self-review report was available. |
| architecture-boundary | 4 | Preserved durable protected binding data and redacted only public projection output. |
| redaction-hygiene | 3 | Implementation redacts locally; controller found the live MCP server still returned stale raw close output before restart. |
| workflow-discipline | 3 | Left useful code and ledger linkage, but the request stayed running until controller cancellation. |
| reviewability | 3 | Diff was easy enough to inspect; missing final summary reduced confidence. |
| runtime-lifecycle | 2 | Harness cleanup required controller cancel plus session close; request had zero reported output while files changed. |
| independence | 3 | Produced most of the fix, but needed controller test hardening and lifecycle cleanup. |

Controller review:

The worker implemented the right shape: `project_public_session()` copies the
session record, replaces the protected binding with `public_binding_projection()`,
and removes top-level legacy provider refs. `close_llm_session()` now projects
live, terminal, and orphaned close results. The controller added missing
assertions that the full `provider-ref-key` does not appear in idempotent and
stale close results.

The self-review instruction did not produce usable signal because the request
remained `running` with no final output. After cancellation, the gateway marked
the request `cancelled` and active session count returned to zero. A live
`agent_llm_session_close` call still returned the old raw close shape, which
indicates the MCP/gateway process was using stale loaded code. Local source
validation still passed after the AS35 change.

Validation repeated by controller:

- `.venv/Scripts/python.exe -m pytest tests/unit/agents/test_agents_gateway_sessions.py tests/unit/agents/test_agents_gateway_recovery.py tests/unit/agents/test_gateway_service_application.py tests/integration/agents/test_gateway_e2e_states.py -q`
- Result: 58 passed
- Gateway cleanup: request cancelled, queues empty, `active-count` 0

Prompting lessons:

- Self-review should be a separate follow-up request on the same session once
  implementation returns, not only a final section in the initial prompt.
- Redaction prompts should require every public path to assert both forbidden
  key names and forbidden full values.
- Harness reviews should distinguish source behavior from currently loaded MCP
  process behavior; close/list tools may need a restart to reflect redaction
  code changes.

## Review: Architecture/Reuse Validation Delegation

- Requests: `req_35c330dab4334dac`, `req_54bd99c2ea23496a`
- Agent profiles: `lite-coder-opencode`, `supp-coder-opencode`
- Plan area: AS gateway/session architecture reuse
- Task class: review-only architecture validation
- Outcome: cancelled by controller; source investigation found gateway observability hid active turn progress

Competency scores:

| Competency | Score | Notes |
| --- | ---: | --- |
| scope-control | 3 | No file edits observed, but no returned review output either. |
| code-correctness | n/a | Review-only task. |
| test-quality | n/a | Review-only task. |
| validation-honesty | 2 | No final report was produced before cancellation, but session timelines later proved both agents were actively working. |
| architecture-boundary | n/a | Could not assess from agent output. |
| redaction-hygiene | 3 | No documented leak by the agents; cleanup again showed stale MCP close output can leak raw internals. |
| workflow-discipline | 2 | Controller had to cancel requests and close sessions. |
| reviewability | 1 | No findings to inspect. |
| runtime-lifecycle | 3 | Both sessions required controller cleanup; active-count returned to zero. The larger issue was request-status observability, not dead workers. |
| independence | 2 | Not usable for this review size/latency budget until live progress is surfaced in status. |

Post-incident correction:

Follow-up investigation showed the earlier "no output" conclusion was only true
for the request records/status API. The session timelines for both requests had
active `session.turn.*` evidence, including model/tool events and terminal
`session.turn.result` events at cancellation time. The real reliability defect
was gateway observability: `request_runtime_status()` did not project persisted
session-turn evidence, and cancelled session turns discarded bounded result
diagnostics from the request record.

Implemented source correction:

- `request_runtime_status()` now includes a redacted `session.latest-turn-event`
  projected from the persisted session timeline.
- Protocol-cancelled session turns preserve bounded `output` and `completion`
  diagnostics when the transport returns terminal result evidence.
- Request attempt schema now accepts `cancelled` attempt state, matching the
  gateway workflow.
- Plan review `RV735` records the SH07 reliability finding.

Controller architecture findings:

1. Medium: session record mutations use an in-process lock, while related
   request and binding stores use foundation cross-process locks.
   `src/audiagentic/components/agents/agents_gateway_sessions_store.py:79`
   creates a `threading.Lock`; `transition_session_record()` and
   `record_session_turn()` use it at lines 289 and 326. By contrast,
   request records use `StartupLock` at
   `src/audiagentic/components/agents/agents_gateway_store.py:88`, and
   binding index writes use `StartupLock` at
   `src/audiagentic/components/agents/agents_gateway_session_bindings.py:317`.
   This may be acceptable if the shared service is the only session mutator,
   but AS08 explicitly expects two-client shared-session behavior and AS30
   requires cross-process race/platform proof for binding/session generation
   work. Recommended next step: either document the single-writer invariant
   in the session store and add a service-level test proving all public session
   mutations route through that writer, or switch session record mutation to a
   per-session `StartupLock` and add a two-process lost-update test.

2. Medium/pending AS31: output streaming still has the legacy environment-gated
   direct append path. `src/audiagentic/components/agents/agents_gateway_dispatch.py:25`
   defines `AUDIAGENTIC_GATEWAY_STREAM_OUTPUT`; `_write_output_chunk()` at line
   28 appends `output.ndjson` directly, with calls at lines 327 and 515. AS31
   already names this as replacement work: add `foundation/transports/agent_output.py`,
   introduce `agents_gateway_output.py`, replace `_write_output_chunk`, remove
   environment-only control, and use typed config plus atomic event-file/index
   storage. Do not patch this opportunistically in unrelated AS items; enforce
   it with AS31 architecture tests that forbid output-file writes outside the
   future output owner.

Compliant reuse observed:

- Request persistence reuses `foundation.io.atomic_write_json`,
  `foundation.contracts.schema_registry.validate_with_schema`, foundation
  workflow transitions, `StartupLock`, and timeline observability.
- Session records reuse schema validation, atomic JSON writes, workflow
  transitions, and timeline observability.
- Binding records reuse the neutral foundation session-binding vocabulary and
  protect binding-index mutations with `StartupLock` plus atomic JSON writes.
- Service host and worker lifecycle use foundation managed-service and
  supervised-process seams rather than a component-local service framework.
- AS34/AS35 source code now uses `peek_session_runtime()` for read-only
  listing and a shared public projection helper for session list/close
  redaction.

Delegation lessons:

- Broad architecture audits are still expensive for the lite/supp profiles when
  the prompt asks them to read many plans and many source files, but they must
  not be judged from blank request output alone. Poll `request_runtime_status()`
  for `session.latest-turn-event` after the SH07 observability fix.
- The focused two-question prompt was better designed but still too slow in
  this production harness. Next attempt should ask for one suspicion only, set
  a small explicit output budget, and include the exact line references already
  gathered by the controller.
- Lower-tier agents look more useful for validating a prepared hypothesis or
  writing focused tests than for discovering architecture issues from a large
  context set. Keep stronger models on design/finding work; delegate narrow
  confirmation and test scaffolding after the controller has done the legwork.
- The stale loaded MCP close behavior repeated during cleanup. Any redaction
  review that uses live gateway tools must note whether the source tree or the
  already-running MCP process is being evaluated.

## Batch: SH07 Worker Fan-Out, RV738-RV740

Three workers were launched in parallel, one per profile:

- `deep-coder-opencode` handled RV738, the continued-session keep-alive
  contract.
- `lite-coder-opencode` handled RV739, the Docker-backed opencode e2e setup
  failure.
- `supp-coder-opencode` handled RV740, an independent review of the SH07/RV735
  observability patch.

Outcomes:

- The three-profile fan-out worked: all lanes ran concurrently and produced
  session timeline evidence while request records were still sparse.
- Session reuse worked for follow-up requests, but the current API cannot
  express "continue this session and keep it alive afterward" until the RV738
  source changes are loaded. A continued request with the flag omitted was
  still recorded as `session-keep-alive: false` in the live gateway process,
  demonstrating the old boundary behavior.
- RV738 needed controller review. The first worker patch correctly removed the
  mutual exclusion but collapsed omitted keep-alive and explicit false. The
  correction introduced nullable `session_keep_alive` / `session-keep-alive`
  so omitted continuation preserves existing behavior, explicit `true` keeps
  the continued session live and allows bounds updates, and explicit `false`
  closes after the turn.
- RV740 was a strong review fit. It found a real duplicate
  `_session_output_from_result()` call and a flaky polling bound. The follow-up
  worker fixed both; controller validation caught an unrelated integration
  regression and the RV738 contract bug.
- RV739 found a real provider descriptor gap: opencode had model projection
  adapters but did not declare `model-projection`, so inventory only exposed
  `pi/custom-entries`. Enabling opencode model projection fixed that setup
  assertion. The worker's initial move to `.opencode/config.json` was wrong for
  the installed opencode CLI; controller corrected model projection and ACP
  launch back to `.opencode/opencode.json`, the file current opencode actually
  loads for project config.

Validation:

- Focused gateway/session/provider validation passed:
  `tests/integration/agents/test_gateway_e2e_states.py`,
  `tests/unit/agents/test_agents_gateway_sessions.py`,
  `tests/unit/agents/test_agents_gateway_store.py`,
  `tests/unit/agents/test_agents_gateway_dispatch_sessions.py`,
  `tests/unit/agents/test_agents_gateway_api.py`,
  `tests/unit/agents/test_agents_gateway_mcp.py`,
  `tests/unit/providers/test_model_sync.py`,
  `tests/unit/providers/test_provider_describe.py`, and
  `tests/unit/providers/test_opencode_mcp_projection.py` all passed in one
  combined run (`159 passed`).
- The Docker-backed opencode e2e now gets past host npm installation and the
  opencode custom-entry inventory assertion, but still fails before hitting the
  rig server. Current opencode reports a generic server error and `rig_requests`
  remains empty. Logs show project `.opencode/opencode.json` is loaded, so the
  remaining blocker is opencode model/provider selection compatibility, not
  Docker isolation.

Harness and observability findings:

- The Docker test's first `EBUSY` was not Docker being locked by an opencode
  session. It was the host harness install step unconditionally running
  `npm install -g opencode-ai` against a global Windows shim. The installer now
  probes `opencode --version` and skips global npm installation when a working
  CLI is already present.
- The opt-in test previously dumped broad home opencode state on failure,
  including auth-shaped files. That debug path was removed; future diagnostics
  should be explicit, redacted, and scoped to the temp project.
- Agent `timeout_seconds` did not act as a hard execution wall for session
  workers. A correction request ran long while continuing to emit timeline
  events; manual cancellation eventually transitioned the request to
  `cancelled` but produced no bounded output. This should feed a future
  gateway control-plane item.
- The live MCP `agent_llm_session_close` response still exposed protected
  binding internals after source redaction changes, confirming the running MCP
  process has stale code loaded. Do not treat live MCP close output as proof
  of the source redaction state until the gateway process is restarted.

Delegation template refinements:

- Give workers code-level instructions and exact files/tests.
- Ask for one focused correction at a time and explicitly tell the worker to
  stop after the fix plus focused validation.
- Reuse sessions for related work, but be careful until the nullable
  keep-alive contract is live in the gateway process.
- Use lower-tier workers for implementation and review of prepared hypotheses;
  controller should keep architecture decisions, final validation, and
  cross-worker conflict resolution.

Follow-up batch, 2026-07-19:

- Launched three more real-work requests:
  - `deep-coder-opencode`: AS21 pure lifecycle/session-decision projector first
    slice.
  - `lite-coder-opencode`: RV739 Docker/opencode model-provider root cause.
  - `supp-coder-opencode`: scoped architecture/reuse/redaction review of the
    current gateway/session/opencode changes.
- The review worker completed in about nine minutes and again performed well as
  a validator. It found an actionable Docker e2e redaction bug: the failure
  diagnostics printed the project opencode config, which could contain the rig
  API key. The controller fixed the test to report only structural fields
  (`config_exists`, selected model, provider ids, and rig request summaries).
- The AS21 and RV739 implementation/investigation workers remained `running`
  beyond two five-minute polling windows with live sessions but zero recorded
  turns. They later completed successfully, so this was not proof of dead
  workers. The gateway lacked an operator-visible in-flight progress signal for
  healthy long-running work. Future orchestration should classify "running
  request + live session + no visible turn progress + stale last-activity" as a
  diagnostic stale-progress condition and surface the latest redacted launch,
  prompt-delivery, model-active, tool-active, or finalizing evidence instead of
  leaving operators with only `attempt.started`.
- Re-ran the Docker e2e after the redaction patch. It still fails before the
  local rig is contacted (`rig_requests` stays empty), but the failure payload
  no longer includes the project config or API key. The run also showed a noisy
  install-time warning from an invalid user-level Gemini MCP JSON file; this is
  not the Docker/opencode blocker.
- Refreshed provider unit validation after the patch:
  `tests/unit/providers/test_opencode_acp.py`,
  `tests/unit/providers/test_model_sync.py`,
  `tests/unit/providers/test_provider_describe.py`, and
  `tests/unit/providers/test_opencode_mcp_projection.py` passed.
- Created SH07 review RV741 to track the product repair: request status, wait,
  and overview should expose a bounded progress projection; wait timeouts should
  return the latest public record plus an explicit timeout marker; and overview
  should expose a live runtime/source fingerprint so stale gateway processes are
  recognizable.

SH07 C2/C6/C11 batch, 2026-07-19:

- Reused all three worker sessions for real SH07 remaining-slice work:
  `deep-coder-opencode` for C2 profile lanes, `lite-coder-opencode` for
  C6/C7/C11 review, and `supp-coder-opencode` for validation/observability.
- The first C2 deep-worker request ended after a context-read preamble and
  produced no implementation. A narrowed follow-up prompt produced useful
  lane-key scaffolding, then self-reviewed the missing stale-generation
  rejection. A third correction added a `SnapshotValidator` seam, snapshot
  identity persistence, and stale-snapshot rejection paths. Assessment:
  capable on implementation after direct constraints, but it needs explicit
  acceptance criteria and must be reviewed against architecture authority
  decisions. It accepted a transitional project-resolved profile model until
  pushed on the gateway-owned registry requirement.
- The lite worker performed well as a focused reviewer. It independently found
  the inverted `replay_required` derivation for `agents.llm.interrupted`,
  corrected the code/tests, and added running/queued recovery event tests. The
  controller also registered missing `CON-AGW-101/102/103` resolutions and
  tightened `link_replay()` so replay linkage is valid only for interrupted
  records that explicitly require replay.
- The supp validation worker was useful for broad but bounded validation. It
  reported focused SH07 units passing, non-Docker gateway e2e passing, Docker
  e2e skipped behind `AUDIAGENTIC_GATEWAY_OPENCODE_DOCKER=1`, and named the
  missing production restart/interrupted-event e2e coverage. It also confirmed
  status/diagnostics now expose live running-job evidence.
- Observability result: after the MCP restart, diagnostics showed live session
  availability, current request id, active turn evidence, latest event
  timestamp, running seconds, and stale-progress. `wait` timeout output was
  still less rich for one long-running request (`phase=launching` without the
  latest session event), so diagnostics/status should remain the controller's
  preferred polling surface until wait projection catches up.
- Harness cleanup/reuse: all three active worker requests reached terminal
  `completed`. The three keep-alive sessions remain live and idle for reuse by
  later related review/correction work. Older active-but-non-live records remain
  visible as `stale-non-live`, which is good observability but still calls for a
  future cleanup/recovery story.

Delegation lessons from this batch:

- Worker prompts for architecture-sensitive code need both the target design
  and explicit non-acceptance cases. For C2, "gateway-owned profile" needed to
  spell out that project-resolved params are only transitional and not
  sufficient for closure.
- Ask workers to self-review, but do not rely on self-review alone. It caught
  the missing stale-generation rejection in C2, while independent review caught
  the inverted replay flag in C11.
- Lower-tier workers are strong for focused validation and bug checks when the
  files/tests and invariants are named. They are weaker at discovering the
  owning authority boundary without controller design prework.
- Keep session reuse for related work. The reused sessions had enough local
  state to move faster and made follow-up correction prompts cheaper.
