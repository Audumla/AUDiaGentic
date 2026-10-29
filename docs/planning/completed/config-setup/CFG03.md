---
id: CFG03
order: 3
plan: config-setup
state: completed
created-at: '2026-10-28T14:11:13.226524+00:00'
breadth: ''
skill: advanced
created-by: claude
priority: P1
work: M
---

# Configuration core: scopes, discovery, merge and validation

## Description

One configuration API: vendor defaults < system < user (platformdirs/XDG) < project (tracked) < project-local < explicit file < CLI. Discovery of project root, one merge rule (per CFG01, likely RFC 7386), strict loader, JSON Schema 2020-12 validation, origin tracking per value, and `config show --origin` / `config validate`. No subsystem migrates yet.

## Steps

1. Implement scope resolution with platformdirs
2. Implement discovery and merge with origin tracking
3. Strict loader and schema validation with exact error locations
4. config show/validate commands

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

tests/unit/foundation/settings/ (test_settings_resolver, test_settings_merge, test_settings_strict_yaml, test_settings_cli): scope order, RFC 7396 merge with provenance, strict YAML (duplicate keys, anchors), schema validation with file/line, and `config show/validate/paths`. Inventory test updated for the new readers.

## Effort & Risk



## Standards



## Acceptance Criteria

Contract tests cover precedence across all scopes, worktree discovery, merge edge cases (lists, null), schema errors with file and line, and `config show --origin` output.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Normative spec: docs/design/configuration-model.md (converged 2026-10-28, GPT rounds 1-3).



Phase 1 (approved 2026-10-28; see 'Phasing' in docs/design/configuration-model.md). Four scopes only: vendor, user, project, explicit; then CLI flags.

2026-10-29: phase 1 merged in PR #90 (59d338649): foundation/config/{settings,merge,strict_yaml}.py and `config show/validate/paths`. System and project-local scopes stay in phase 2.

## Change Log

- 2026-10-28T14:11:13.226524+00:00 (created-by): Created by claude
- 2026-10-28T14:11:15.584906+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:43.654789+00:00 (updated-by): Updated: section:notes
- 2026-10-28T22:06:49.138977+00:00 (updated-by): Updated: section:notes
- 2026-10-28T22:07:07.753716+00:00 (state-transition): State: pending → in_progress
- 2026-10-29T01:56:02.719048+00:00 (updated-by): Updated: section:validation, section:notes
- 2026-10-29T01:56:05.033130+00:00 (state-transition): State: in_progress → completed
