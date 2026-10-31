---
id: CFG07
order: 7
plan: config-setup
state: pending
created-at: '2026-10-28T21:05:48.895276+00:00'
breadth: ''
skill: advanced
created-by: claude
work: M
priority: P2
---

# Qualification evidence store and qualify command

## Description

Platform and surface qualification comes from evidence records, not hand-edited packaged descriptors (gpt_auto.yaml platforms). `audiagentic qualify <provider>` runs the live acceptance and writes a versioned record to state; releases ship vendor evidence. Shares the evidence schema with SH53.

## Steps

1. Evidence schema shared with SH53
2. qualify command over existing live acceptance tests
3. Surface resolver reads evidence instead of descriptor platform lists
4. Explicit allow-unqualified override reported by doctor

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation



## Effort & Risk



## Standards



## Acceptance Criteria

Running `audiagentic qualify gpt-auto` on Linux makes the gpt-auto-cdp surface resolvable there with no package edit.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Normative spec: docs/design/configuration-model.md (converged 2026-10-28, GPT rounds 1-3).



Phase 2: deferred until needed (see 'Phasing' in docs/design/configuration-model.md). PR #82 covers gpt-auto on Linux meanwhile.

## Change Log

- 2026-10-28T21:05:48.895276+00:00 (created-by): Created by claude
- 2026-10-28T21:05:51.231491+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:48.314949+00:00 (updated-by): Updated: section:notes
- 2026-10-28T22:07:03.106732+00:00 (updated-by): Updated: section:notes
