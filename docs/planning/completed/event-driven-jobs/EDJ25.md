---
id: EDJ25
order: 66
plan: plan-event-driven-jobs
state: completed
validate-first: true
priority: P2
complexity: mid
created-by: claude
---

# Integrate prompt context + template rendering into direct job launches

## Description

RV247 confirmed: prompt_launch.py's launch_prompt_request/_build_job_from_request never import build_prompt_context_from_request, never render templates, and never load session input — direct CLI/MCP/API launches bypass the EDJ10 context layer entirely, so only event-triggered jobs get context-rendered prompts. Additionally prompt-launch-request.schema.json (BOTH the component copy and the foundation mirror) still requires prompt-body and lacks agent-profile-id / context / prompt-template-file fields, so the direct-launch surface cannot even accept the new capabilities.

## Steps

1. Schema first. Component copy `components/agent_jobs/contracts/prompt-launch-request.schema.json` is authoritative; edit it, copy bytes verbatim to foundation mirror, then run mirror-drift test. Remove `prompt-body` from `required`; add `prompt-template-file`, optional `agent-profile-id`, optional `context` object with `additionalProperties: true`; add top-level `oneOf` requiring exactly one of prompt-body/prompt-template-file. Preserve all unrelated schema requirements and `additionalProperties: false`.
2. Extract shared `load_prompt_template_file(project_root: Path, template_path: str, *, owner_id: str) -> str` from `event_triggers.py` into `prompt_templates.py`. It owns `ensure_contained`, IO-PTMPL-001/002, IO-PATH-001 behavior. Replace trigger loader call with it; no duplicate containment logic in prompt_launch.
3. In `launch_prompt_request`, after parsed request and resolved job/provider/profile values exist but before `build_job_record` persists launch request, obtain source text (inline body or shared file loader), load session using `load_session_data(project_root, session_id)` when source session-id is non-empty, build `build_prompt_context_from_request`, and render with `render_prompt_template(source_text, to_template_dict(context))`.
4. Caller `context` merges only into the context builder's metadata section exactly as `build_prompt_context_from_request` already defines; do not introduce a second merge policy. Template-free inline text must remain byte-identical after render. Persist only rendered prompt body in launch-request; do not persist raw template contents or caller context.
5. Characterize current inline direct-launch behavior before edits. Tests cover each schema XOR case, file template success, dotted placeholders using caller context, session data, inline passthrough, containment escape, missing file, unresolved placeholder, and byte-identical mirror. Existing direct launch tests remain green.
6. No new rendering engine, no event-observer imports, no duplicated template/file helper.

## Files

src/audiagentic/components/agent_jobs/prompt_launch.py
src/audiagentic/components/agent_jobs/prompt_context.py
src/audiagentic/components/agent_jobs/contracts/prompt-launch-request.schema.json
src/audiagentic/foundation/contracts/schemas/prompt-launch-request.schema.json
tests/unit/jobs/test_prompt_launch.py

## Validation

Tests: direct launch with prompt-template-file renders through the shared context (job's launch-request carries the rendered body); inline prompt-body with placeholders + caller context renders; template-free prompt-body passes through unchanged (regression: ALL existing direct-launch tests stay green); both/neither of prompt-body/template-file rejected by schema; session input loaded when session-id present; containment escape rejected; schema mirror-drift test passes.

## Effort & Risk

Medium. The regression surface is every existing direct launch — the no-placeholder passthrough behavior is the compatibility keystone; characterize it first. Reuse the event-trigger loading/rendering functions; zero duplicated containment or rendering logic.

## Standards

arch-standards — registered error codes, no logic duplication, schema mirror rule.
component-creation — one rendering pipeline for all launch surfaces.

## Notes

From review RV247 (codex). After this lands, event-triggered and direct launches share one context/render pipeline — EDJ09's docs should describe that single pipeline, not two.

## Ledger Events

- chg_20260712_051854_make-event-driven-job-work-ite_9726
- chg_20260712_053919_direct-climcpapi-job-launche_2651
