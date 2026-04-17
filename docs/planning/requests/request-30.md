---
id: request-30
label: Expose planning config for agents
state: closed
summary: Add read-only Planning API and MCP surface that exposes effective live creation/config
  requirements so agents know what kinds they can create and what each kind requires
source: codex
guidance: standard
current_understanding: Initial intake captured; requirements are understood well enough
  to proceed.
open_questions:
- What exact outcome is required?
- What constraints or non-goals apply?
- How will success be verified?
standard_refs:
- standard-1
spec_refs:
- spec-4
---




# Understanding

Planning API and planning MCP already enforce creation rules from config, but agents do not have one cheap read path that explains current creation contract.

Today an agent can discover some behavior indirectly from docs, schemas, or trial/error through `tm_create` validation. That is weak for autonomous use because agent needs to know, before creating or editing items:
- what kinds exist
- which kinds support domains
- what refs are required per kind
- what optional fields are allowed
- what profiles and guidance levels exist
- what document templates / required sections apply
- what relationship rules and workflow defaults are active

# Problem

Planning system lacks a dedicated read method that exposes effective live configuration in agent-friendly form.

Current shortcomings:
1. Agents must infer creation contract from multiple files or errors.
2. `tm_create` validates inputs, but does not help enough before mutation.
3. Config-driven planning is harder to use safely without a discovery endpoint.
4. Different kinds have different required refs and workflow semantics, but there is no single read surface for that.
5. This increases invalid create attempts and weakens agent autonomy.

# Desired Outcome

Add a read-only Planning API / MCP method that exposes current effective configuration for agent consumption.

Observable outcomes:
1. Agent can query supported kinds and creation requirements before calling `tm_create`.
2. Response includes per-kind fields such as dir, id prefix, domain support, required refs, optional fields, required sections, and relationship rules.
3. Response includes available profiles, guidance levels, default profile, default guidance, and workflow names/defaults.
4. Response is cheap, structured, and safe to call often.
5. MCP guidance can point agents to this method before mutation, reducing trial-and-error.

# Constraints

- Read-only surface only.
- Must reflect live config from project root, not hardcoded defaults.
- Keep output compact enough for agent use.
- Prefer one coherent API/MCP surface over forcing agents to read raw YAML files.
- Stay aligned with existing config-driven planning design.

# Verification Expectations

1. Agent can query creation requirements for each planning kind without mutation.
2. Output matches live project config.
3. Output is structured enough to drive creation prompts/tooling.
4. Docs/MCP guidance updated to reference new read method.
5. Tests cover shape and correctness of returned config summary.

# Notes

## Proposed Direction

Most efficient design is a cheap read-only config surface for agents, preferably `tm_docs op=config` or equivalent compact schema tool.

Recommended behavior:
- default `mode=compact`
- optional `kind` filter
- optional `include_templates=false` by default
- return compact structured JSON, not long prose

Recommended compact payload:
- top-level defaults: default profile, default guidance
- per-kind creation contract: create support, has_domain, required_fields, optional_fields, required_refs, state_on_create
- agent-facing usage string per kind
- available profiles and guidance levels
- template section names only in compact mode
- optional higher-cost `mode=full` for relationship rules, workflow defaults, standards defaults, and template bodies

Agent workflow target:
1. call config tool once in compact mode
2. choose kind and required refs
3. call `tm_create` with valid fields first try
4. optionally request `mode=full kind=<kind>` when richer body/template detail needed

Design goal: low token, machine-usable, cacheable for session, reduces invalid create attempts.
