---
id: CFG06
order: 6
plan: config-setup
state: in_progress
created-at: '2026-10-28T21:05:44.274107+00:00'
breadth: ''
skill: intermediate
created-by: claude
work: M
priority: P1
---

# Separate provider enabled, available and qualified

## Description

Provider enablement becomes user configuration (default auto), availability is a runtime check, qualification is evidence. Remove persisted probe results under .audiagentic/config/runtime/features/ so a provider without a CLI (gpt-auto) is never disabled by a probe. Coordinates with PC10 and DI01.



Also: provider instances under providers.<id>.instances, selected by agents with `instance`; retire config/providers/gpt_auto_t1.yaml and gpt_auto_t2.yaml (aliases of one CDP implementation targeting different ChatGPT projects). Acceptance adds: two ChatGPT projects use one provider descriptor.

## Steps

1. Config key providers.<id>.enabled: auto|true|false
2. Availability checks owned by each provider
3. Remove feature-state persistence and its legacy migration
4. Align PC10/DI01

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation



## Effort & Risk



## Standards

docs/design/configuration-model.md (Providers: enabled is policy, available is observed, qualified is evidence); docs/standards/ARCHITECTURE_STANDARDS.md section 2 (configuration, not central lists) and section 3 (ownership); docs/standards/ARCHITECTURE_GUIDELINES.md section 8 (lazy, cached loaders), section 9 (no compatibility paths without a recorded obligation; the one-release transition is recorded in the design doc Migration section) and section 10 (callers outside providers use providers_api).

## Acceptance Criteria

On a clean install, gpt-auto is usable without any enablement step, and disabling a provider in config is the only way it becomes disabled.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Phase 2: deferred until needed (see 'Phasing' in docs/design/configuration-model.md). PR #84 already stops probes disabling providers without a CLI probe.

2026-10-29: slice 1 in PR #126: providers settings section with providers.<id>.enabled (auto|true|false); is_provider_usable for runtime gates falls back to the provider availability check under auto, so a clean install needs no enablement step. Remaining: stop probe-driven disables in reconcile and retire persisted feature-state files; provider instances (gpt_auto_t1/t2).

2026-10-29: slices 1 and 2 merged (PRs #126, #131). providers.<id>.enabled (auto|true|false) is settings policy; runtime gates use is_provider_usable (policy, else persisted enablement, else the provider availability check), so a clean install needs no enablement step; a failed CLI probe no longer disables a provider or prunes surfaces (reconcile reports unavailable). Remaining: retire the persisted provider feature-state files and their legacy migration; provider instances (gpt_auto_t1/t2 become providers.gpt-auto.instances, selected by agents with instance). Tests: tests/unit/providers/test_provider_enabled_policy.py, test_provisioning.py, test_reconciliation_policy_enforcement.py.

2026-10-30: provider instances in PR (branch cfg06-instances): `providers.<id>.instances.<name>` overlays one provider's options; agents select with `instance`; `ProviderTarget` key `provider@instance` separates sessions/queue/evidence while descriptor, adapter, enabled policy and availability resolve to the provider. gpt_auto_t1/t2 and descriptor `extends:` (#202) deleted. GPT review (REVISE) findings applied except folding the per-provider option files into settings, deferred to the provider-settings migration. Remaining: that migration, and retiring the persisted provider feature-state shards (settings per-provider options, launch.py shard check). Local live-test config must move to providers.gpt-auto.instances.

2026-10-30: generic settings writer (foundation/config/writer.py, yaml_edit.py) and `audiagentic config set` landed in the settings-writer PR. GPT review (APPROVE PR A with safety fixes) applied: lock held outside the repo, hash re-check before replace (refuse, never overwrite a human edit), candidate parsed by the strict loader and validated by the section schemas, exact-merge-result check, scope rules enforced in the writer (`x-audiagentic-scopes` on gateway/home), symlink refusal, bounded 0600 backups, mode preservation, cache invalidation via the existing file stamp. PR B (provider enable/disable via the writer, deleting the providers shard) stays deferred until the shard inventory and migration contract exist: enabled flag AND shard options must be classified first; no shard fallback without an approved obligation.

2026-10-31 GPT on-track review (verdict ADJUST; the architecture and spec remain sound). Delivered: provider policy in settings, provider instances (replacing the t1/t2 alias descriptors), the generic settings writer and `config set`, and the harness endpoint rename. NOT delivered, and CFG06 must not be marked complete until it is: the provider feature-state shard (.audiagentic/config/runtime/features/providers.yaml) is still a second authority. It holds `enabled`, `options` (validated against the descriptor options_schema) and per-feature enable state (feature_resolution), and is the shared foundation.features mechanism also used by coding_lsp, memory, planning and gateway; the per-provider option files also still sit beside settings. Moving only `enabled` would leave two authorities. The consolidation (inventory of fields and consumers, destination keys, precedence, migration, rollback, removal criteria, GPT review) is owned by CFG11, and is a completion dependency of CFG06.

Progress 2026-10-31: the provider shard's `enabled` flag is no longer configuration (local observation, #284) and provider options, policy and model sources are settings (#285, #287), so the dual authority for provider policy and options is gone. What keeps this item open: per-component options and feature state still sit in the shards (see CFG11 remaining item 3), and the qualification evidence (CFG07) is not done.

## Change Log

- 2026-10-28T21:05:44.274107+00:00 (created-by): Created by claude
- 2026-10-28T21:05:46.585356+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:34.290936+00:00 (updated-by): Updated: section:description
- 2026-10-28T22:07:00.801522+00:00 (updated-by): Updated: section:notes
- 2026-10-29T03:06:35.428651+00:00 (updated-by): Updated: section:notes
- 2026-10-29T03:06:37.786536+00:00 (state-transition): State: pending → in_progress
- 2026-10-29T04:00:56.152954+00:00 (updated-by): Updated: section:notes
- 2026-10-29T04:21:46.043510+00:00 (updated-by): Updated: section:standards

## Ledger-events

- chg_20261031_010914_settings-can-be-written-with-c_3841
- 2026-10-31T01:09:16.752705+00:00 (updated-by): Updated: section:ledger-events
- 2026-10-31T03:42:11.610783+00:00 (updated-by): Updated: section:notes
- 2026-10-31T07:11:01.301957+00:00 (updated-by): Updated: section:notes
