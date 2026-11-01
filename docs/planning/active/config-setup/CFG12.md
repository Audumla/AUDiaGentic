---
id: CFG12
order: 0
plan: config-setup
state: pending
created-at: '2026-10-31T12:21:43.390702+00:00'
breadth: ''
skill: ''
created-by: agent
priority: P3
work: M
---

# Live qualification probes and measured vendor platform claims

## Description

audiagentic qualify runs only default checks (CLI installed, adapter resolves). Add per-provider live acceptance probes over the existing live tests (for example tests/gpt_auto/test_session_transport_live.py) so a record proves behaviour, and replace unmeasured vendor platform claims in descriptors with measured evidence or remove them.

## Steps



## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Unit tests for the probe hook; a documented live run per provider with a probe.

## Effort & Risk



## Standards

docs/design/configuration-model.md (Qualification evidence: evidence, not hand-edited descriptors); docs/standards/ARCHITECTURE_STANDARDS.md section 3 (ownership: providers own their probes) and section 2 (configuration, not central lists); docs/standards/ARCHITECTURE_GUIDELINES.md section 9 (no compatibility paths); reuse the CFG07 platform record and the SH53 evidence schema, no parallel store.

## Acceptance Criteria

qualify runs a provider's live acceptance probe when its prerequisites exist and records the outcome; every vendor platform claim in a descriptor cites a measured run or is removed.

## Notes

2026-11-01 GPT design review (round 13). SLICE CFG12-A DONE in this change: `audiagentic qualify --live PROVIDER` (explicit, needs a provider; the default qualify is unchanged and runs no probes). providers/services/qualification/live.py: static LIVE_TARGETS dispatch, ProbeOutcome (capability, proven, registered reason, bounded observations), qualify_live(): inventory -> disposable scratch dir -> provider probe -> one immutable SH53 evidence record (exact executable digest + adapter digest + native schema; proof artifact-digest over the observations) -> scratch removed. A capability is true only when proven; a crashed or timed-out probe is `probe-failed` (never evidence of absence); state is supported only when the strict join set is proven, partial when anything is, unsupported only for explicitly unsupported reasons, otherwise inconclusive. Every record carries the claim: native protocol behaviour of this exact executable/adapter/schema on a disposable environment, not vendor-model, authentication or human-UI proof. REMAINING for CFG12: probes for the other providers (SH55/SH56) and replacing unmeasured vendor platform claims in descriptors with measured evidence or removing them, which depend on those probes. Rules from the review kept: static dispatch, no registry; live tests opt-in (pytest -m opt_in), never in default CI; allowlisted environment with no credentials; own-PID process groups only.

## Change Log

- 2026-10-31T12:21:43.390702+00:00 (created-by): Created by agent
- 2026-10-31T12:30:22.445841+00:00 (updated-by): Updated: section:standards
- 2026-11-01T06:04:51.073202+00:00 (updated-by): Updated: section:notes
