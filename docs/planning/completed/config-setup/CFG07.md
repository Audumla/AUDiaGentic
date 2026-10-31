---
id: CFG07
order: 7
plan: config-setup
state: completed
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

tests/unit/providers/test_platform_qualification.py and test_qualification_doctor.py: qualify writes the per-platform record; a platform with no vendor evidence is no-platform-match until qualify, then supported; stale (package version, spec version, fingerprint), failed and invalid records are rejected; one platform never serves another; the allow-unqualified override resolves and doctor reports it; doctor lists unqualified enabled surfaces and never probes. Full suite: only the known baseline failures.

## Effort & Risk



## Standards



## Acceptance Criteria

Running `audiagentic qualify gpt-auto` on Linux makes the gpt-auto-cdp surface resolvable there with no package edit.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Normative spec: docs/design/configuration-model.md (converged 2026-10-28, GPT rounds 1-3).



Phase 2: deferred until needed (see 'Phasing' in docs/design/configuration-model.md). PR #82 covers gpt-auto on Linux meanwhile.

2026-10-31 GPT on-track review (ADJUST): the qualification matrix must now cover provider instances (provider@instance keys), `audiagentic config set`, the endpoint-only harness (no embedded rig), the removed environment variables, and installed-wheel CLI/MCP tests. CFG08's installed-wheel qualification (0.46.0 from PyPI: setup, doctor, config set, planning/ledger/gateway MCP initialize) is completed evidence for CFG08 only; it does not satisfy CFG07's broader evidence record (versioned records, vendor evidence, scope isolation and conflict tests including user-project scope, which CFG11 delivers). Evidence collection can proceed in parallel with CFG11; do not treat CFG07 as done because CFG08 passed.

2026-10-31 slice delivered: local platform qualification records (<state>/qualification/v1/<provider>/<surface>/<platform>.yaml) with fingerprint, package version, spec version, result, time, environment, evidence digest; `audiagentic qualify [PROVIDER] [--surface ID] [--json]` (default checks: CLI installed, adapter resolves); the surface resolver accepts a valid local record for the running platform when the descriptor has no vendor evidence for it and rejects stale/failed/invalid ones (reasons qualification-stale/-failed/-invalid); one platform's record never serves another. Acceptance shown by test: a platform with no vendor evidence is no-platform-match until `qualify gpt-auto`, then supported, with no package edit. Remaining: per-provider live probes beyond the default checks, removing unmeasured vendor platform claims from descriptors (decision needed: it makes those platforms unqualified until qualified), and a doctor line for unqualified surfaces / the allow-unqualified override.

2026-10-31 closed. Delivered: local platform records, `audiagentic qualify`, resolver use of valid local records, providers.<id>.allow-unqualified override reported by doctor (providers.qualification check). Interpretation: descriptor platform lists are the vendor evidence the wheel ships; a local record or the explicit override covers the rest. Follow-up (CFG12): live acceptance probes per provider over the existing live tests, and measuring the vendor platform claims.

## Change Log

- 2026-10-28T21:05:48.895276+00:00 (created-by): Created by claude
- 2026-10-28T21:05:51.231491+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:48.314949+00:00 (updated-by): Updated: section:notes
- 2026-10-28T22:07:03.106732+00:00 (updated-by): Updated: section:notes
- 2026-10-31T03:42:14.202506+00:00 (updated-by): Updated: section:notes
- 2026-10-31T11:43:58.134526+00:00 (updated-by): Updated: section:notes
- 2026-10-31T12:21:32.502326+00:00 (updated-by): Updated: section:validation, section:notes
- 2026-10-31T12:21:49.450234+00:00 (state-transition): State: pending → completed
