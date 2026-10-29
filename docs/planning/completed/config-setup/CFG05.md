---
id: CFG05
order: 5
plan: config-setup
state: completed
created-at: '2026-10-28T21:05:39.635274+00:00'
breadth: ''
skill: advanced
created-by: claude
work: M
priority: P1
---

# Agent definitions as single validated files with templates

## Description

Replace the four cross-referenced catalog records (prompt, role, execution profile, agent) with one schema-validated file per agent in any scope, provider defaults (a provider with one surface needs no surface field), and customisable packaged templates (per CFG01, likely single-level `extends`). Fields aligned with A2A Agent Card names so SH61 can project them.

## Steps

1. Agent schema and loader
2. Provider defaults and template resolution
3. agent list/show --resolved/add
4. Migration from ~/.audiagentic/config/agents.yaml

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

tests/unit/agents/test_agent_files.py (15 tests): schema validation, scope layering, single-level extends with null deletes, surface defaulting, compile to catalog records, `agent list|show|add`.

## Effort & Risk



## Standards



## Acceptance Criteria

A five-line gpt-auto agent file validates in the editor and CLI, resolves to the same execution as today's catalog entry, and an invalid field fails at load with its file and line.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Normative spec: docs/design/configuration-model.md (converged 2026-10-28, GPT rounds 1-3).



Phase 1 (approved 2026-10-28; see 'Phasing' in docs/design/configuration-model.md).



2026-10-28: implemented in PR #98 (stacked on #90): agent files + templates (vendor config/components/agents/templates, user and project agents/ and templates/), canonical agent-file schema, RFC 7396 layering with single-level extends (null deletes inherited fields), surface defaulting via providers_api.list_session_surface_ids, compile_catalog to existing records, 'audiagentic agent list|show|add'. 15 tests.

2026-10-29: merged in PR #98 (53fbfdb00).

## Change Log

- 2026-10-28T21:05:39.635274+00:00 (created-by): Created by claude
- 2026-10-28T21:05:41.961814+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:45.989964+00:00 (updated-by): Updated: section:notes
- 2026-10-28T22:06:53.809848+00:00 (updated-by): Updated: section:notes
- 2026-10-28T23:29:43.309575+00:00 (updated-by): Updated: section:notes
- 2026-10-28T23:29:45.626295+00:00 (state-transition): State: pending → in_progress
- 2026-10-29T01:56:07.380146+00:00 (updated-by): Updated: section:validation, section:notes
- 2026-10-29T01:56:09.712383+00:00 (state-transition): State: in_progress → completed
