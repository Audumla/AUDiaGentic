---
id: CFG01
order: 1
plan: config-setup
state: completed
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

docs/design/configuration-model.md is merged; the child items are completed; the remaining aim is tracked in CFG13-CFG16.

## Effort & Risk



## Standards



## Acceptance Criteria

- The converged specification is recorded in docs/design/configuration-model.md with decisions and rejected alternatives
- CFG02-CFG11 were implemented from it and are completed
- The end-to-end aim (simple setup, no duplicated facts) is NOT claimed by this item: it is verified by the acceptance criteria of CFG13-CFG16

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Normative spec: docs/design/configuration-model.md (converged 2026-10-28, GPT rounds 1-3). Decisions: strict YAML 1.2 + JSON Schema; scopes vendor < system(--config only) < user < project(current checkout) < user-project (<user-config>/projects/<id>.yaml) < --config < CLI; RFC 7396 merge; typed credential refs; provider instances; single-level extends; three public env vars. Awaiting owner review before CFG03.

Closed with qualification (2026-10-31). Completing the isolated configuration items did not deliver the primary aim: CFG10 added a third source for one gateway connection. The aim is an end-to-end outcome (a new local project and gateway need zero hand-edited files; remote and multi-project setups need only inputs that cannot be derived). CFG13-CFG16 own it.

## Change Log

- 2026-10-28T14:11:03.758900+00:00 (created-by): Created by claude
- 2026-10-28T14:11:06.121991+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:29.614285+00:00 (updated-by): Updated: section:notes
- 2026-10-28T21:21:52.991408+00:00 (state-transition): State: pending → in_progress
- 2026-10-31T23:04:49.558509+00:00 (updated-by): Updated: section:validation, section:acceptance_criteria, section:notes
- 2026-10-31T23:05:04.456608+00:00 (state-transition): State: in_progress → completed
