---
id: CFG02
order: 2
plan: config-setup
state: completed
created-at: '2026-10-28T14:11:08.485354+00:00'
breadth: ''
skill: intermediate
created-by: claude
priority: P1
work: S
---

# Inventory configuration readers, writers and environment variables

## Description

Produce the executable inventory the migration depends on: every config reader and writer (today 9 modules use foundation/config/layers.py, 49 files build .audiagentic paths themselves), every packaged config file, every generated project file, and all 86 AUDIAGENTIC_* env vars classified as user config, deployment wiring, internal plumbing or test-only.

## Steps

1. Script the inventory from source
2. Classify env vars and readers by subsystem
3. Commit it as a checked fixture with a test that fails when a new unclassified reader or env var appears

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

tests/unit/architecture/test_config_inventory.py checks config_inventory.yaml against an AST scan of the source tree (env var names, classification, .audiagentic path builders); runs in CI on every PR.

## Effort & Risk



## Standards



## Acceptance Criteria

A unit test fails when a new AUDIAGENTIC_* env var or ad-hoc .audiagentic path is added without being classified.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Normative spec: docs/design/configuration-model.md (converged 2026-10-28, GPT rounds 1-3).



Implemented in PR #83 (tests/unit/architecture/config_inventory.yaml + test_config_inventory.py): 83 AST-verified names (47 user-config, 10 deployment, 12 internal, 13 test, 1 not-env), 49 path-builder modules.

2026-10-29: merged in PR #83 (11db8b611).

## Change Log

- 2026-10-28T14:11:08.485354+00:00 (created-by): Created by claude
- 2026-10-28T14:11:10.866332+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:41.322771+00:00 (updated-by): Updated: section:notes
- 2026-10-28T21:21:55.339481+00:00 (state-transition): State: pending → in_progress
- 2026-10-28T21:21:57.675342+00:00 (updated-by): Updated: section:notes
- 2026-10-29T01:55:58.057102+00:00 (updated-by): Updated: section:validation, section:notes
- 2026-10-29T01:56:00.389287+00:00 (state-transition): State: in_progress → completed
