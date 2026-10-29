---
id: CFG04
order: 4
plan: config-setup
state: completed
created-at: '2026-10-28T14:11:17.938532+00:00'
breadth: ''
skill: intermediate
created-by: claude
priority: P1
work: S
---

# Tracked project configuration and stable project identity

## Description

Split .audiagentic/ into tracked project config and ignored local/state, so worktrees and clones share project config with no bootstrap. Project identity: declared id, else git origin repository name (PR #81), else the CFG01 decision for no-remote repositories.



Also: user-project overrides at <user-config>/projects/<project-id>.yaml, loaded after tracked project settings, path-safe ids with collision checks, reported as scope user-project by config show --origin. Project scope is the current checkout's .audiagentic/settings.yaml, never the git common directory.

## Steps

1. Define tracked vs ignored paths and update .gitignore guidance
2. Identity resolution per CFG01
3. Migrate project.yaml readers to the core API

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

tests/unit/project/test_project_identity.py (PR #113): a real `git worktree` of a configured repository resolves the same project id and settings as the main checkout with no setup; git-remote ids shared by worktrees and normalized path-safe; declared id beats legacy and git; doctor reports provisional and ambiguous identity. tests/unit/contracts/test_repository_hygiene.py covers the tracked/ignored .gitignore split.

## Effort & Risk



## Standards



## Acceptance Criteria

A fresh worktree of a configured repository resolves the same project id and settings as the main checkout with no setup command.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Phase 1 (approved 2026-10-28; see 'Phasing' in docs/design/configuration-model.md). Phase 1 covers tracked project settings and identity; the user-project scope (projects/<id>.yaml) moves to phase 2.

2026-10-29: phase 1 in PR #113: project_id() (settings, legacy project-id, git origin name, main checkout), doctor warns on provisional or ambiguous identity, .gitignore keeps .audiagentic/settings.yaml, agents/ and templates/ tracked, docs/guides/PROJECT_SETTINGS.md. Remaining (phase 2): user-project scope and project.yaml reader migration.

2026-10-29: phase 1 merged in PR #113.

2026-10-29: completed for phase 1 (PR #113). Phase 2: user-project scope (<user config>/projects/<id>.yaml) and migrating the remaining project.yaml readers (gateway workspace-label matching, prompt_launch, onboarding) to the resolver.

## Change Log

- 2026-10-28T14:11:17.938532+00:00 (created-by): Created by claude
- 2026-10-28T14:11:20.306536+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:31.957780+00:00 (updated-by): Updated: section:description
- 2026-10-28T22:06:51.492273+00:00 (updated-by): Updated: section:notes
- 2026-10-29T02:22:49.606500+00:00 (updated-by): Updated: section:notes
- 2026-10-29T02:39:26.475219+00:00 (updated-by): Updated: section:notes
- 2026-10-29T03:28:44.690274+00:00 (updated-by): Updated: section:validation, section:notes
- 2026-10-29T03:28:47.042056+00:00 (state-transition): State: pending → completed
