---
id: CFG09
order: 9
plan: config-setup
state: completed
created-at: '2026-10-28T21:05:58.219424+00:00'
breadth: ''
skill: advanced
created-by: claude
work: L
priority: P2
---

# Migrate remaining subsystems to the configuration core

## Description

Move each remaining reader to the core API one subsystem per PR, deleting its files: gateway (incl. shared server/node config), model sources (PC12), provider settings and overlays (including gpt_auto_t1/t2 as configured instances), interoperability, component markers, logging, rig. Provide `config migrate` with backup.



Also covers model sources (PC12) and shared gateway server/node config; legacy readers stay until migration and rollback tests pass.

## Steps

1. One PR per subsystem with its deletions
2. config migrate with backup and dry-run
3. Old-path read with warning for one release

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Phase 1 (PRs #101, #114): tests/unit/agents/test_effective_catalog.py (agent files merged with the legacy catalog, clashes reported) and tests/unit/agents/test_gateway_settings.py (gateway section precedence, legacy env override, policy digest parity with the legacy JSON, ambiguity makes the policy invalid). CFG02 inventory test stays green.

## Effort & Risk



## Standards



## Acceptance Criteria

Phase 1 (approved scope: agent catalog and gateway configuration): agent files are read through the effective catalog and the main-side gateway settings come from the `gateway` settings section, with legacy sources honoured for one release. The original criterion (the CFG02 inventory shows zero ad-hoc .audiagentic path builders outside the core API) is NOT met and moves to phase 2 together with providers, model sources, interoperability, logging, rig, component markers, `config migrate`, and the shared server/node config (on the shared-gateway plan branch).

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Phase 1 (approved 2026-10-28; see 'Phasing' in docs/design/configuration-model.md). Phase 1 migrates the agent catalog and gateway configuration only; providers, model sources, interoperability, logging and rig follow in phase 2.



2026-10-29: part 1 in PR #101 (stacked on #100): read-only EffectiveAgentsRepository merges legacy agents.yaml with compiled machine-scope agent files (agent files win clashes; agents.yaml optional once agent files exist); used by read_global_agents_config, agent composition, context opening and the gateway profile registry; management CRUD unchanged; doctor agents.catalog warns on clashes. Project-scope agent files not in the machine catalog yet. Remaining CFG09: providers, model sources, interoperability, shared server/node config (phase 2).

2026-10-29: part 2 in PR #114: agents-owned gateway settings section (implementation, port, idle grace, queue backend, restart wait, embedded coexistence, console trace, dashboard window, retention and watchdog policies) via gateway/settings.py; legacy AUDIAGENTIC_GATEWAY_* variables override for one release; legacy gateway policy JSON read only when its section is absent. Deferred: shared server/node config (shared_config.py on the shared-gateway plan branch) migrates when that branch lands on main.

2026-10-29: part 1 merged in PR #101.

2026-10-29: part 2 (gateway settings) merged in PR #114. Phase 1 of CFG09 is complete.

2026-10-29: completed for phase 1 only (see Acceptance Criteria); phase 2 remainder is explicit there.

## Change Log

- 2026-10-28T21:05:58.219424+00:00 (created-by): Created by claude
- 2026-10-28T21:06:00.565183+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:38.970334+00:00 (updated-by): Updated: section:description
- 2026-10-28T22:06:58.485387+00:00 (updated-by): Updated: section:notes
- 2026-10-28T23:39:31.620807+00:00 (updated-by): Updated: section:notes
- 2026-10-28T23:39:33.972906+00:00 (state-transition): State: pending → in_progress
- 2026-10-29T02:22:51.943173+00:00 (updated-by): Updated: section:notes
- 2026-10-29T02:26:58.030377+00:00 (updated-by): Updated: section:notes
- 2026-10-29T02:39:28.790216+00:00 (updated-by): Updated: section:notes
- 2026-10-29T03:28:49.375412+00:00 (updated-by): Updated: section:validation, section:acceptance_criteria, section:notes
- 2026-10-29T03:28:51.703687+00:00 (state-transition): State: in_progress → completed
