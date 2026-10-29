---
id: CFG01
order: 1
plan: config-setup
state: in_progress
created-at: '2026-10-28T14:11:03.758900+00:00'
breadth: ''
skill: advanced
created-by: claude
priority: P1
work: M
---

# Converge the configuration and setup specification

## Description

Run the critical GPT review rounds to one converged specification: scopes and precedence, discovery, merge rule, file format, file layout, config/state/cache split, templates, provider activation and qualification, credentials, env vars, CLI, deletion list and plan mapping. Record every decision with its rejected alternatives. Later CFG items implement this spec and are refined from it.

## Steps

1. Finish GPT round 2 and push back on unverified claims
2. Decide each disagreement in the round-2 list with a recommendation
3. Write the converged spec to docs/design/configuration-model.md
4. Update CFG02-CFG10 from the spec

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation



## Effort & Risk



## Standards



## Acceptance Criteria

docs/design/configuration-model.md exists, every decision lists rejected alternatives, and CFG02-CFG10 reference its sections.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Normative spec: docs/design/configuration-model.md (converged 2026-10-28, GPT rounds 1-3). Decisions: strict YAML 1.2 + JSON Schema; scopes vendor < system(--config only) < user < project(current checkout) < user-project (<user-config>/projects/<id>.yaml) < --config < CLI; RFC 7396 merge; typed credential refs; provider instances; single-level extends; three public env vars. Awaiting owner review before CFG03.

## Change Log

- 2026-10-28T14:11:03.758900+00:00 (created-by): Created by claude
- 2026-10-28T14:11:06.121991+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:29.614285+00:00 (updated-by): Updated: section:notes
- 2026-10-28T21:21:52.991408+00:00 (state-transition): State: pending → in_progress
