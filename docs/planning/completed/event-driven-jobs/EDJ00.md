---
id: EDJ00
order: 0
plan: plan-event-driven-jobs
state: completed
validate-first: false
priority: P1
work: S
created-by: claude
---

# Event-driven jobs — plan overview and implementation order

## Description

Coordination artifact for the event-driven-jobs plan (pattern: RS00). Read this FIRST before implementing any EDJ item. Goal: configured event-bus triggers launch durable agent jobs whose instructions are dispatched to the agents LLM gateway asynchronously, with outcomes propagated back to job state and full correlation/observability end-to-end. Architecture in one paragraph: agent-jobs subscribes to configured event patterns (EDJ01/EDJ02), renders a prompt from a stable context (EDJ06/EDJ10/EDJ11), creates a durable job record with event provenance (EDJ03), dispatches by PUBLISHING `agents.llm.gateway.requested` — never by importing agents' API (EDJ04) — and applies gateway lifecycle outcomes to job state (EDJ05). Standards/primitives that gate the spine: schema ownership (EDJ19), shared operational-record writer (EDJ20), async error standard + dead-letter (EDJ12), canonical timelines (EDJ07). Design-decision items (EDJ08/EDJ13/EDJ15/EDJ21) produce documented decisions, not speculative code.

## Steps

ALL PHASES COMPLETE — 2026-07-12.

COMPLETED (spine): EDJ19+EDJ17, EDJ01, EDJ06, EDJ10, EDJ20, EDJ12, EDJ02, EDJ11, EDJ07, EDJ03, EDJ04, EDJ05, EDJ22. Deleted as superseded: EDJ16 (→EDJ20), EDJ18 (→EDJ21).

PHASE R (remediation) — completed 2026-07-12 in order: EDJ23 (observer correctness: per-trigger subscription, disabled-trigger loader+suppression audit, metadata copies, never-raise outcome handler with pre-dispatch guard, dispatch-failure job lifecycle + created/ready→failed workflow edges), EDJ24 (summarize_structure/safe_metadata/is_sensitive_key in foundation redaction; recursive CON-OPR-002 denylist), EDJ25 (schema oneOf prompt-body/prompt-template-file + agent-profile-id + context; direct launches render through the shared context pipeline; template-free inline bodies byte-identical; trigger loader deduped onto load_prompt_from_file).

PHASE F (features) — completed 2026-07-12: EDJ08 (agents.llm.gateway.cancel-requested topic + handler in agents; control.py publishes after persisted cancellation; job.gateway-cancel-requested timeline event), EDJ14 (event_overview.event_jobs_overview + jobs_store.list_job_records + new jobs_mcp.py read-only tool), EDJ15 (filter conditions: schema $defs, foundation resolve_path/_MISSING extraction, matches_filter, suppressed/reason=filter audit), EDJ09 (README event-driven-jobs doctrine with test-backed YAML example).

PHASE D (design) — completed 2026-07-12: EDJ13 (tests/unit/jobs/test_gateway_boundary.py + docs/design/gateway-shared-service.md decision record; all follow-up rows none), EDJ21 (STOP decision: consolidation rejected by the characterization gate; test_actions_render_compat.py retained as permanent compatibility guard).

SEQUENCE DEVIATIONS / DISCOVERIES: (1) EDJ14's "existing agent-jobs MCP server" and "existing jobs-store list API" did not exist — created thin jobs_mcp.py mirroring agents_gateway_mcp and added jobs_store.list_job_records. (2) EDJ25 compatibility: rendering is gated on placeholder presence (foundation.templates.has_placeholders) so template-free inline bodies stay byte-identical; inline bodies containing {…} now render (unresolved paths raise VAL-TPL-001) — inherent in the item's design. (3) EDJ24's recursive denylist reuses the shared is_sensitive_key matcher per spec (broader than the old four exact field names); all current append_operational_record callers audited safe. (4) EDJ21 ended in its documented stop branch — a decision, not code.

## Files



## Validation

All EDJ items completed or deleted/superseded. Final sweep 2026-07-12: tests/unit/jobs, tests/unit/agents, foundation logging/operational-records/templates/actions-render-compat/schema-mirror-drift/workflow, integration prompt-launch + job-control — all green (3 environment skips: symlink privileges x2, win32 echo capture). Pre-existing failures unrelated to this plan (planning-API created-by fixture, baseline skill assets, foundation.interaction approvals, hindsight toolchain gates) noted to the user.

## Effort & Risk

None — coordination artifact only; no code.

## Standards

arch-standards; observability-standards; component-creation — the per-item standards fields are authoritative; this item just indexes them.

## Notes

Reviews: RV230/231/232, RV250-254, RV255 (EDJ22 lifecycle fix), RV256-263 (implementation-readiness lock) — all closed. Current verdict: completed spine sound after EDJ22; remaining work is implementation-ready. EDJ08/13/14/15/21/23/24/25 now name exact owners, configuration/schema boundaries, contracts, failure paths, reuse seams, stop conditions, and validation. EDJ09 needs only documentation after its named dependencies land. Accepted deviations: dispatch source `event-trigger:<trigger-id>`; audit field `status`; outcome matching uses metadata job-id only. Re-verify named modules if tree drifts.

## Ledger Events


