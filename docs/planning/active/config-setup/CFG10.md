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

docs/design/configuration-model.md (environment variables: three public names plus XDG_*, private _AUDIAGENTIC_ prefix for internal plumbing, test switches stay test-scoped); docs/standards/ARCHITECTURE_STANDARDS.md and ARCHITECTURE_GUIDELINES.md: one configuration authority, no parallel loaders or compatibility paths without an approved obligation, delete obsolete code in the same change, evidence-led scope (tests/unit/architecture/config_inventory.yaml tracks progress).

## Acceptance Criteria

The CFG02 inventory test lists no public AUDIAGENTIC_* variable outside the CFG01 allowlist.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Normative spec: docs/design/configuration-model.md (converged 2026-10-28, GPT rounds 1-3).



Phase 2: deferred until needed (see 'Phasing' in docs/design/configuration-model.md).

2026-10-31 slice 1 (rig residue, no legacy path, approved by the user): the harness `rig:` section is now `endpoint:` (url, model, provider) in config/provisioning/harness/ag.yaml. Deleted: local_rig_host, local_rig_port, require_harness_rig_port (replaced by require_harness_endpoint, which validates endpoint.url), AUDIAGENTIC_RIG_HOST, AUDIAGENTIC_RIG_PORT, AUDIAGENTIC_RIG_BASE_URL (three env names out of the config inventory), and the stale rig READMEs. The seeded model source `ag-rig` is now `ag-endpoint` (base-url from endpoint.url, no env override). No fallback reader: a project that still sets `rig:` in .audiagentic/config/harness/ag.yaml is no longer read, and an `ag-rig` entry already written to a project's model sources stays there as an orphan until removed by hand. Remaining behaviour-switch variables for later slices: AUDIAGENTIC_AG_* (base url, model, provider, enable_mcp), AUDIAGENTIC_AI_AUDIT*, AUDIAGENTIC_LOG_*, AUDIAGENTIC_LOCALE, AUDIAGENTIC_GATEWAY_PORT, AUDIAGENTIC_AUTO_UPDATE_ENABLED, AUDIAGENTIC_LOCAL_PROVIDER_BASE_URL, AUDIAGENTIC_RECONCILE_PROVIDERS_ON_LAUNCH, AUDIAGENTIC_STARTUP_STATUS. CFG10 stays pending: the design gates the full reduction on every entrypoint using the resolver (CFG09).

2026-10-31 slice 2 (AG_* inputs, no legacy path): removed the user-facing AUDIAGENTIC_AG_BASE_URL, AUDIAGENTIC_AG_MODEL, AUDIAGENTIC_AG_PROVIDER and AUDIAGENTIC_AG_ENABLE_MCP overrides (4 names out of the inventory) and the env_flag helper. The harness endpoint, model, provider and mcp.enabled come only from the layered harness config (package default, user-global ag.yaml, project-local ag.yaml). The launcher passes the endpoint and model it resolved to its child processes through the private _AUDIAGENTIC_HARNESS_ENDPOINT / _AUDIAGENTIC_HARNESS_MODEL variables (foundation/config/harness.py ENDPOINT_ENV, MODEL_ENV); the inventory scan ignores the underscore-prefixed internal namespace by design. build_global_context(enable_mcp=...) now defaults to False and the launcher no longer reads an env flag. AUDIAGENTIC_AG_SMOKE_TIMEOUT stays a test switch. Remaining behaviour switches: AI_AUDIT*, LOG_*, LOCALE, GATEWAY_PORT, AUTO_UPDATE_ENABLED, LOCAL_PROVIDER_BASE_URL, RECONCILE_PROVIDERS_ON_LAUNCH, STARTUP_STATUS.

2026-10-31 GPT on-track review (ADJUST). Slices 1 (rig residue) and 2 (AUDIAGENTIC_AG_*) are consistent with the spec: isolated removals are acceptable before CFG09 when they cannot interfere with migration or rollback, but CFG10 stays formally blocked on CFG11 (CFG09 phase 2) and on resolver coverage across every supported entrypoint. Remaining behaviour switches to disposition individually (each must end as an approved public exception, an `_AUDIAGENTIC_` internal, a deployment-only variable, or a settings key; AUDIAGENTIC_LOG_LEVEL stays the documented diagnostic exception): AI_AUDIT*, LOG_*, LOCALE, GATEWAY_PORT, AUTO_UPDATE_ENABLED, LOCAL_PROVIDER_BASE_URL, RECONCILE_PROVIDERS_ON_LAUNCH, STARTUP_STATUS; 6 deployment and 12 internal variables stay classified in config_inventory.yaml. Open check from the review: confirm the layered harness config (package/user/project ag.yaml via load_layered_config) honours the canonical resolver and provenance rules rather than being a separate resolution mechanism; if not, migrate it under CFG11. Logging/audit slices follow the CFG11 provider migration design unless an independently safe slice is ready.

## Change Log

- 2026-10-28T21:06:02.889937+00:00 (created-by): Created by claude
- 2026-10-28T21:06:05.222566+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:50.653458+00:00 (updated-by): Updated: section:notes
- 2026-10-28T22:07:05.424881+00:00 (updated-by): Updated: section:notes
- 2026-10-31T02:25:32.424561+00:00 (updated-by): Updated: section:notes
- 2026-10-31T03:16:24.025032+00:00 (updated-by): Updated: section:notes
- 2026-10-31T03:33:38.394009+00:00 (updated-by): Updated: section:standards
- 2026-10-31T03:42:19.336440+00:00 (updated-by): Updated: section:notes
