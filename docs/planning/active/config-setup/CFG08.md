---
id: CFG08
order: 8
plan: config-setup
state: in_progress
created-at: '2026-10-28T21:05:53.564412+00:00'
breadth: ''
skill: intermediate
created-by: claude
work: M
priority: P1
---

# setup and doctor commands, MCP registration without env

## Description

`audiagentic setup` is idempotent: creates only needed user config, registers MCP servers in detected harnesses through the CLI entrypoint (no interpreter paths, no env vars), and runs doctor. `audiagentic doctor` checks every failure seen on 2026-10-28 and prints the exact fix.



Also: installed-wheel qualification (clean Python 3.10 wheel install passes setup, MCP and gateway smoke tests); feeds SH42. CFG07 must land first.

## Steps

1. doctor checks: config validity, agents, provider availability/qualification, project identity, MCP registration, package data, gateway reachability
2. setup flow over existing mcp install
3. MCP entries via `audiagentic mcp <id>`

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation



## Effort & Risk



## Standards

docs/design/configuration-model.md (phased spec); docs/standards/ARCHITECTURE_STANDARDS.md and ARCHITECTURE_GUIDELINES.md: foundation owns mechanics (strict YAML, merge, schema registry, platform paths), components own their own checks and settings sections, no parallel loaders. Read-only doctor; setup writes only the user settings scope. Error codes registered with resolutions.

## Acceptance Criteria

On a clean container, `audiagentic setup` followed by one agent_task_submit to a gpt-auto agent succeeds with no manual file edits.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Phase 1 (approved 2026-10-28; see 'Phasing' in docs/design/configuration-model.md). Installed-wheel qualification without CFG07 evidence.



2026-10-29: PR #100 (stacked on #98): audiagentic doctor (read-only, no app graph) running component-declared checks from config/components/<component>/doctor/checks.yaml via foundation.config.refs; checks: package.data, settings.valid (foundation), project.identity, mcp.onboarding (project), agents.files, provider.<id> availability (agents; new providers_api.check_provider_availability incl. gpt-auto CDP probe). audiagentic setup creates only missing user settings then runs doctor. Not yet: MCP registration through the CLI entrypoint (needs the providers MCP writer change) and installed-wheel qualification.

2026-10-29: merged in PR #100 (squash). Validation: tests/unit/foundation/test_doctor.py (component-declared checks, read-only doctor, idempotent setup, crashing check reported not raised).

## Change Log

- 2026-10-28T21:05:53.564412+00:00 (created-by): Created by claude
- 2026-10-28T21:05:55.898893+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:36.632840+00:00 (updated-by): Updated: section:description
- 2026-10-28T22:06:56.145222+00:00 (updated-by): Updated: section:notes
- 2026-10-28T23:39:26.834124+00:00 (updated-by): Updated: section:notes
- 2026-10-28T23:39:29.268659+00:00 (state-transition): State: pending → in_progress
- 2026-10-29T02:22:47.262707+00:00 (updated-by): Updated: section:notes
