# Packet Dependency Graph

## Purpose

Provide the transitive dependency view for packet readiness. A packet may not start until all direct and transitive dependencies are merged.

## Readiness rule

A packet is **ready** only when:
- direct dependencies are merged
- transitive dependencies are merged
- any contract freeze point for the ownership group has passed

While `Phase 0.3` is active, no new non-refactor packet claim should start unless the live registry explicitly exempts it. Treat that checkpoint freeze as an additional global readiness rule on top of packet-local dependency edges.

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
  FND9 --> FND10[PKT-FND-010]
  FND10 --> FND11[PKT-FND-011]
  FND11 --> FND12[PKT-FND-012]
  FND12 --> FND13[PKT-FND-013]
  FND9 --> LFC9[PKT-LFC-009]
  FND9 --> RLS10[PKT-RLS-010]
  RLS6 --> RLS11[PKT-RLS-011]
  RLS8 --> RLS11
  LFC3 --> RLS11
  RLS11 --> LFC11[PKT-LFC-011]
  LFC11 --> LFC12[PKT-LFC-012]
  FND13 --> LFC12
  LFC12 --> LFC13[PKT-LFC-013]
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
  PRV31 --> PRV48[PKT-PRV-048]
  PRV22 --> PRV48
  PRV48 --> PRV49[PKT-PRV-049]
  PRV5 --> PRV49
  PRV32 --> PRV49
  PRV48 --> PRV50[PKT-PRV-050]
  PRV9 --> PRV50
  PRV37 --> PRV50
  PRV48 --> PRV51[PKT-PRV-051]
  PRV31 --> PRV51
  PRV51 --> PRV52[PKT-PRV-052]
  PRV5 --> PRV52
  PRV32 --> PRV52
  PRV51 --> PRV53[PKT-PRV-053]
  PRV9 --> PRV53
  PRV37 --> PRV53
  PRV33[PKT-PRV-033] --> PRV55[PKT-PRV-055]
  PRV31 --> PRV59[PKT-PRV-059]
  PRV31 --> PRV60[PKT-PRV-060]
  PRV59 -.infrastructure.-> NOD1[PKT-NOD-001]
  PRV60 -.infrastructure.-> NOD1
  P4S((Phase 4 stabilization checkpoint)) --> NOD1
  NOD1 --> NOD2[PKT-NOD-002]
  NOD1 --> NOD3[PKT-NOD-003]
  NOD1 --> DIS1[PKT-DIS-001]
  DIS1 --> DIS2[PKT-DIS-002]
  DIS1 --> DIS3[PKT-DIS-003]
  NOD1 --> EVT1[PKT-EVT-001]
  DIS1 --> EVT1
  EVT1 --> EVT2[PKT-EVT-002]
  EVT1 --> CRD1[PKT-CRD-001]
  CRD1 --> EXT1[PKT-EXT-001]
```

## Clarification on extension ordering

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
2. `PKT-PRV-032` (Codex Option A baseline)
3. `PKT-PRV-033` (Claude Option A baseline)
4. `PKT-PRV-034` (Gemini)
5. `PKT-PRV-035` (Copilot)
6. `PKT-PRV-036` (Continue)
7. `PKT-PRV-037` (Cline)
8. `PKT-PRV-038` (local-openai/Qwen)

Note: `PKT-PRV-055` is Claude Option B (native hook) follow-on, depends on PKT-PRV-033 VERIFIED.

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

`.8` is the project release bootstrap extension tracked under Phase 2.3, so it is not repeated in this provider-facing cluster.

Phase 0.3 is the repository-structure checkpoint that should complete before additional non-refactor implementation resumes. Its intended order is:

1. `PKT-FND-010`
2. `PKT-FND-011`
3. `PKT-FND-012`
4. `PKT-FND-013`

Phase 1.4 is the installability correction layer that follows Phase 1 and Phase 2.3. Its intended order is:

1. `PKT-LFC-011`
2. `PKT-LFC-012`
3. `PKT-LFC-013`

`.9` adds live stream and progress capture after the trigger layer is already frozen and the shared stream contract is written down. The intended order is:

1. `PKT-PRV-048`
2. `PKT-PRV-049`
3. `PKT-PRV-050`
4. `PKT-PRV-072`
5. `PKT-PRV-073`

`.10` adds live input and interactive session control after live-stream capture is already frozen and the shared input contract is written down. The intended order is:

1. `PKT-PRV-051`
2. `PKT-PRV-052`
3. `PKT-PRV-053`

`.11` adds structured completion and result normalization after the live input/capture path is already frozen and the shared result contract is written down. The first packetized implementation order is:

1. `PKT-PRV-056`
2. `PKT-PRV-057`
3. `PKT-PRV-058`

`.12` adds provider optimization and shared workflow extensibility after the completion contract is written down. This phase is currently docs-only, so it does not yet introduce new packet ids.

`PKT-PRV-059` is centralized prompt syntax and alias configuration infrastructure. It depends on PKT-PRV-031 (shared bridge) and is available to all providers automatically through the shared prompt parser. It is infrastructure-level and does not block provider implementations.

`PKT-PRV-012` no longer depends on `PKT-JOB-007`; the earlier apparent cycle is resolved by treating provider/model field names as provider-owned contract output first.

The later node/discovery/federation/connectors extension line is separate from the provider line and begins only after the Phase 4 provider/runtime stabilization checkpoint. Its intended order is:

1. `PKT-NOD-001`
2. `PKT-NOD-002`
3. `PKT-NOD-003`
4. `PKT-DIS-001`
5. `PKT-DIS-002`
6. `PKT-DIS-003`
7. `PKT-EVT-001`
8. `PKT-EVT-002`
9. `PKT-CRD-001`
10. `PKT-EXT-001`

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
