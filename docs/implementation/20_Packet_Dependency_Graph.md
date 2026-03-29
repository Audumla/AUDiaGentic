# Packet Dependency Graph

## Purpose

Provide the transitive dependency view for packet readiness. A packet may not start until all direct and transitive dependencies are merged.

## Readiness rule

A packet is **ready** only when:
- direct dependencies are merged
- transitive dependencies are merged
- any contract freeze point for the ownership group has passed

## High-level dependency graph

```mermaid
graph TD
  FND2[PKT-FND-002] --> LFC1[PKT-LFC-001]
  FND5[PKT-FND-005] --> LFC1
  FND6[PKT-FND-006] --> LFC1
  LFC1 --> LFC2[PKT-LFC-002]
  LFC2 --> LFC3[PKT-LFC-003]
  LFC3 --> RLS1[PKT-RLS-001]
  RLS1 --> RLS2[PKT-RLS-002]
  RLS2 --> RLS3[PKT-RLS-003]
  RLS3 --> RLS4[PKT-RLS-004]
  RLS4 --> RLS5[PKT-RLS-005]
  RLS5 --> RLS6[PKT-RLS-006]
  RLS6 --> RLS7[PKT-RLS-007]
  RLS7 --> RLS8[PKT-RLS-008]
  RLS3 --> JOB1[PKT-JOB-001]
  JOB1 --> JOB2[PKT-JOB-002]
  JOB2 --> JOB3[PKT-JOB-003]
  JOB3 --> JOB4[PKT-JOB-004]
  JOB4 --> JOB5[PKT-JOB-005]
  JOB5 --> JOB6[PKT-JOB-006]
  PRV1[PKT-PRV-001] --> PRV2[PKT-PRV-002]
  JOB3 --> PRV2
  PRV2 --> PRV10[PKT-PRV-010]
```

## Clarification on Phase 3 and Phase 4

`PKT-JOB-003` uses a **stub/mock provider seam only**. `PKT-PRV-002` and `PKT-PRV-010` attach real provider selection and health-check behavior in Phase 4 without changing Phase 3 job contracts.

## Validator requirement

`tools/validate_packet_dependencies.py` must:
- fail on unknown packet ids
- fail on direct circular dependencies
- detect forward-phase references without a seam note
- emit a topological order report

## DRAFT future enhancements

- merge-queue suggestion output
- owner readiness dashboard
