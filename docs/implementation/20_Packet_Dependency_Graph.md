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
  PRV2 --> PRV11[PKT-PRV-011]
  PRV11 --> PRV12[PKT-PRV-012]
  FND7[PKT-FND-007] --> FND8[PKT-FND-008]
  PRV12 --> FND8
  FND8 --> JOB7[PKT-JOB-007]
  LFC7[PKT-LFC-007] --> LFC8[PKT-LFC-008]
  FND8 --> LFC8
  RLS8[PKT-RLS-008] --> RLS9[PKT-RLS-009]
  FND8 --> RLS9
  FND8 --> FND9[PKT-FND-009]
  PRV12 --> FND9
  FND9 --> LFC9[PKT-LFC-009]
  FND9 --> RLS10[PKT-RLS-010]
  JOB6 --> JOB7
  JOB7 --> JOB8[PKT-JOB-008]
  FND9 --> JOB8
  LFC9 --> JOB8
  JOB8 --> JOB9[PKT-JOB-009]
  RLS10 --> JOB9
  JOB9 --> JOB10[PKT-JOB-010]
  PRV12 --> PRV14[PKT-PRV-014]
  FND9 --> PRV14
  LFC9 --> PRV14
  RLS10 --> PRV14
  JOB8 --> PRV14
  JOB9 --> PRV14
  PRV14 --> PRV15[PKT-PRV-015]
  PRV5[PKT-PRV-005] --> PRV15
  PRV14 --> PRV16[PKT-PRV-016]
  PRV4[PKT-PRV-004] --> PRV16
  PRV14 --> PRV17[PKT-PRV-017]
  PRV6[PKT-PRV-006] --> PRV17
  PRV14 --> PRV18[PKT-PRV-018]
  PRV7[PKT-PRV-007] --> PRV18
  PRV14 --> PRV19[PKT-PRV-019]
  PRV8[PKT-PRV-008] --> PRV19
  PRV14 --> PRV20[PKT-PRV-020]
  PRV9[PKT-PRV-009] --> PRV20
  PRV14 --> PRV21[PKT-PRV-021]
  PRV3[PKT-PRV-003] --> PRV21
  PRV11[PKT-PRV-011] --> PRV21
  PRV12 --> PRV22[PKT-PRV-022]
  PRV13 --> PRV22
  PRV14 --> PRV22
  PRV22 --> PRV23[PKT-PRV-023]
  PRV15 --> PRV23
  PRV22 --> PRV24[PKT-PRV-024]
  PRV16 --> PRV24
  PRV22 --> PRV25[PKT-PRV-025]
  PRV17 --> PRV25
  PRV22 --> PRV26[PKT-PRV-026]
  PRV18 --> PRV26
  PRV22 --> PRV27[PKT-PRV-027]
  PRV19 --> PRV27
  PRV22 --> PRV28[PKT-PRV-028]
  PRV20 --> PRV28
  PRV22 --> PRV29[PKT-PRV-029]
  PRV21 --> PRV29
  PRV22 --> PRV30[PKT-PRV-030]
  PRV21 --> PRV30
```

## Clarification on .1 and .2 extension ordering

`.1` freezes provider/model contract fields before jobs or prompt launch consume them.
The intended order is:

1. `PKT-PRV-012`
2. `PKT-FND-008`
3. `PKT-JOB-007`
4. `PKT-FND-009`
5. `PKT-LFC-009`
6. `PKT-RLS-010`
7. `PKT-JOB-008`
8. `PKT-JOB-009`

`.3` adds shorthand/default-launch ergonomics after the core `.2` path is verified. The intended order is:

1. `PKT-JOB-010`

`.4` adds provider prompt-tag surface synchronization after the core `.2` path is verified. The intended order is:

1. `PKT-PRV-014`
2. `PKT-PRV-015`
3. `PKT-PRV-016`
4. `PKT-PRV-017`
5. `PKT-PRV-018`
6. `PKT-PRV-019`
7. `PKT-PRV-020`
8. `PKT-PRV-021`

`.5` adds provider tag execution compliance and isolated provider implementation docs after the `.4` surface contract is frozen. The intended order is:

1. `PKT-PRV-022`
2. `PKT-PRV-023`
3. `PKT-PRV-024`
4. `PKT-PRV-025`
5. `PKT-PRV-026`
6. `PKT-PRV-027`
7. `PKT-PRV-028`
8. `PKT-PRV-029`
9. `PKT-PRV-030`

`.6` adds provider prompt-trigger launch behavior after the shared launch grammar and provider execution layer are already frozen. The intended order is:

1. `PKT-PRV-031`
2. `PKT-PRV-032`
3. `PKT-PRV-033`
4. `PKT-PRV-034`
5. `PKT-PRV-035`
6. `PKT-PRV-036`
7. `PKT-PRV-037`
8. `PKT-PRV-038`

`.7` adds provider availability and auto-install orchestration after the trigger layer and provider execution layer are already frozen. The intended order is:

1. `PKT-PRV-039`
2. `PKT-PRV-040`
3. `PKT-PRV-041`
4. `PKT-PRV-042`
5. `PKT-PRV-043`
6. `PKT-PRV-044`
7. `PKT-PRV-045`
8. `PKT-PRV-046`
9. `PKT-PRV-047`

`PKT-PRV-012` no longer depends on `PKT-JOB-007`; the earlier apparent cycle is resolved by treating provider/model field names as provider-owned contract output first.

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
