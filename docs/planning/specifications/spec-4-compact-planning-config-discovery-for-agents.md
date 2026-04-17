---
id: spec-4
label: Compact planning config discovery for agents
state: draft
summary: Define a low-token read-only config surface that tells agents what planning
  kinds exist and what each kind requires for valid creation
request_refs:
- request-30
task_refs: []
standard_refs:
- standard-6
- standard-5
---






# Purpose
Provide a cheap read-only planning config discovery surface so agents can learn the current creation contract before calling `tm_create` or other planning mutation tools.
# Scope
- Add one read-only MCP/API surface for planning config discovery
- Default to low-token compact mode for frequent agent use
- Support optional higher-detail mode for deeper planning config inspection
- Expose enough per-kind data to form valid `tm_create` calls on first try
- Update MCP guidance/docs to point agents to this discovery path before mutation

Out of scope:
- changing planning creation rules
- replacing existing YAML config files
- adding new planning object kinds as part of this task
# Requirements
## Surface

The implementation should expose a read-only config summary through either:
- `tm_docs op=config`, or
- an equivalent dedicated read tool if that fits the current surface better

The surface must read live project config from the active root.

## Compact Mode

Default mode should be optimized for low token use and agent consumption.

Compact output must include:
- top-level defaults: default profile and default guidance
- supported planning kinds
- for each kind:
  - whether creation is supported
  - whether domain is supported
  - required fields
  - optional fields
  - required refs
  - state on create
  - required section names or template section names only
  - short agent-facing usage hint showing a valid create pattern
- available profiles and guidance levels

## Full Mode

Optional higher-cost mode should expose deeper planning detail only when requested.

Full mode should include, at minimum where available:
- relationship rules
- workflow defaults / named workflows
- standard defaults
- richer template details or full template bodies

## Output Shape

Output should be structured, machine-usable JSON rather than long prose.
Output should be stable enough for agents to cache for a session.

## Agent UX

The response should help an agent answer two questions cheaply:
1. What kind of planning object can I create here?
2. What exact fields/refs do I need to provide for a valid create call?
# Constraints
- Read-only behavior only; no mutation side effects
- Must reflect live config from project root, not hardcoded defaults
- Keep compact mode small enough for frequent agent use
- Prefer one coherent discovery surface over requiring agents to read raw YAML
- Stay aligned with existing config-driven planning design and validation rules
# Acceptance Criteria
1. Agent can query current creation requirements for each planning kind without mutation.
2. Compact output is sufficient to form valid `tm_create` calls for request, spec, plan, task, wp, and standard.
3. Compact output includes default profile, default guidance, and per-kind usage hints.
4. Optional fuller mode exposes deeper relationship/workflow/template detail only when requested.
5. Returned config summary matches live project config.
6. MCP guidance/docs reference this discovery path as the preferred pre-mutation read step.
7. Tests verify output shape and correctness against current config.
