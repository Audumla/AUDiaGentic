---
id: task-12
label: Implement agent-facing planning config discovery
state: done
summary: Add compact read-only config discovery so agents know valid planning object
  creation requirements before using tm_create
domain: core
spec_ref: spec-4
standard_refs:
- standard-0005
- standard-0006
---








# Objective
Implement a read-only planning config discovery surface that gives agents low-token, machine-usable creation guidance before they call planning mutation tools.
# Deliverables
- Add a read-only config discovery surface, preferably `tm_docs op=config` unless a dedicated read tool is a better fit for the current MCP surface
- Implement default compact mode optimized for frequent agent use
- Support optional fuller mode for deeper config inspection
- Return structured JSON with per-kind creation contract and usage hints
- Update MCP guidance/docs so agents are directed to this read path before `tm_create`
- Add tests that verify output shape and correctness against live config
# Acceptance Criteria
1. Agents can query supported planning kinds and current creation requirements without mutation.
2. Compact output is sufficient to form valid `tm_create` calls for request, spec, plan, task, wp, and standard.
3. Compact output includes default profile, default guidance, and one short usage hint per kind.
4. Optional fuller mode exposes deeper relationship/workflow/template detail only when requested.
5. Returned config summary matches live project config from the active root.
6. MCP guidance/docs reference this discovery path as the preferred pre-mutation read step.
7. Tests verify output shape and correctness against current config.
# Implementation Notes

Preferred compact output should include:
- default profile
- default guidance
- supported kinds
- per-kind: create support, domain support, required fields, optional fields, required refs, state on create, section/template names, and a short usage hint
- available profiles and guidance levels

Optional fuller mode should include deeper config detail such as:
- relationship rules
- workflow defaults / named workflows
- standard defaults
- richer template details or template bodies

Keep compact mode small and cacheable for an agent session.
Do not require agents to read raw planning YAML files for normal create-path discovery.
