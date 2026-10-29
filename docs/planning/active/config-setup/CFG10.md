---
id: CFG10
order: 10
plan: config-setup
state: pending
created-at: '2026-10-28T21:06:02.889937+00:00'
breadth: ''
skill: intermediate
created-by: claude
work: S
priority: P2
---

# Reduce public environment variables to a handful

## Description

Keep only the public variables chosen in CFG01 plus XDG_*; turn configuration-in-disguise variables into settings keys, rename internal plumbing to a documented internal prefix, and keep test switches test-scoped.

## Steps

1. Apply CFG02 classification
2. Settings keys for config vars
3. Internal prefix for plumbing
4. One release of honoured-with-warning

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation



## Effort & Risk



## Standards



## Acceptance Criteria

The CFG02 inventory test lists no public AUDIAGENTIC_* variable outside the CFG01 allowlist.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Normative spec: docs/design/configuration-model.md (converged 2026-10-28, GPT rounds 1-3).



Phase 2: deferred until needed (see 'Phasing' in docs/design/configuration-model.md).

## Change Log

- 2026-10-28T21:06:02.889937+00:00 (created-by): Created by claude
- 2026-10-28T21:06:05.222566+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:50.653458+00:00 (updated-by): Updated: section:notes
- 2026-10-28T22:07:05.424881+00:00 (updated-by): Updated: section:notes
