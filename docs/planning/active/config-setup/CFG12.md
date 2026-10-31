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



## Change Log

- 2026-10-31T12:21:43.390702+00:00 (created-by): Created by agent
- 2026-10-31T12:30:22.445841+00:00 (updated-by): Updated: section:standards
