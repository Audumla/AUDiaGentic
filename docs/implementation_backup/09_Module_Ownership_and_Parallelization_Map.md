# Module Ownership and Parallelization Map

## Purpose

Allow multiple implementors to work in parallel without stomping on shared contracts or tracked file ownership.

## Hard rule

Only one packet owns a contract or tracked file writer at a time.
If two packets need the same contract, one packet must finish first and publish the stable interface.

## Ownership groups

### Group A — contracts and scaffolding
Owns:
- `docs/specifications/architecture/03_Common_Contracts.md`
- `docs/specifications/architecture/18_File_Ownership_Matrix.md`
- `docs/specifications/architecture/19_Glossary.md`
- `src/audiagentic/contracts/schemas/`
- `docs/examples/fixtures/`
- validator scripts and CLI stubs

Parallelism:
- PKT-FND-001 and PKT-FND-003 may run in parallel
- PKT-FND-002 depends on canonical ids from PKT-FND-001
- PKT-FND-005 depends on schemas and examples from PKT-FND-002/004

### Group B — lifecycle
Owns:
- lifecycle command module(s)
- install manifest writes
- `.audiagentic/project.yaml` initialization
- workflow detection/rename logic
- migration reports

Parallelism:
- PKT-LFC-001 and PKT-LFC-002 must finish first
- PKT-LFC-003 and PKT-LFC-004 can then proceed in parallel
- PKT-LFC-005, 006, 007 depend on detection + checkpoints

### Group C — release and ledger
Owns:
- `.audiagentic/runtime/ledger/`
- `docs/releases/CURRENT_RELEASE_LEDGER.ndjson`
- `docs/releases/CURRENT_RELEASE.md`
- `docs/releases/CHECKIN.md`
- `docs/releases/AUDIT_SUMMARY.md`
- `docs/releases/CHANGELOG.md`
- `docs/releases/LEDGER.ndjson`
- Release Please managed files

Parallelism:
- PKT-RLS-001 and PKT-RLS-006 can start after Phase 1
- PKT-RLS-002 depends on RLS-001
- PKT-RLS-003/004 depend on RLS-002
- PKT-RLS-005 depends on RLS-003/004/006
- PKT-RLS-007 depends on RLS-001 data shape and lifecycle migration rules

### Group D — jobs
Owns:
- job state store
- packet runner
- workflow profile engine
- stage output storage

Parallelism:
- PKT-JOB-001 and PKT-JOB-002 can start together after Phase 2
- PKT-JOB-003 depends on JOB-001/002
- PKT-JOB-004/005/006 depend on JOB-003

### Group E — providers and optional server
Owns:
- provider registry and selection
- provider adapters
- optional server seam draft
- provider model catalog and selection extensions (Phase 4.1)
- provider status/validation CLI (Phase 4.2)
- provider prompt-tag surface integration and synchronization (Phase 4.3)
- provider tag execution compliance and isolated per-provider implementation docs (Phase 4.4)
- provider prompt-trigger launch behavior and bridge/wrapper rollout (Phase 4.6)
- provider availability and auto-install orchestration (Phase 4.7)

Parallelism:
- PKT-PRV-001 and PRV-002 first
- provider adapters can then run in parallel
- optional server seam is last and must not change provider adapter contracts

### Group F — Discord
Owns:
- Discord overlay adapter
- Discord event consumer
- Discord approval action handler

Parallelism:
- all Discord packets depend on finalized approval/event/release contracts
- Discord packets can run in parallel with migration hardening only

## Contract freeze points

- Freeze 1: end of Phase 0 — common contracts, ids, schemas
- Freeze 2: end of Phase 1 — lifecycle CLI and state detection
- Freeze 3: end of Phase 2 — release file ownership and ledger semantics
- Freeze 4: end of Phase 3 — job state and workflow stage contract
- Freeze 5: end of Phase 4 — provider and optional server seam
- Freeze 5.1: end of Phase 4.1 — provider model catalog and selection contract
- Freeze 5.2: end of Phase 4.2 — provider status/validation contract
- Freeze 5.3: end of Phase 4.3 — provider prompt-tag surface contract
- Freeze 5.4: end of Phase 4.4 — provider execution compliance and isolated provider implementation contract
- Freeze 5.5: end of Phase 4.6 — provider prompt-trigger launch bridge contract
- Freeze 5.6: end of Phase 4.7 — provider availability and auto-install contract

## What implementors must not do

- do not edit tracked release file ownership rules outside the release packets
- do not add new provider ids without updating common contracts and the naming validator first
- do not modify lifecycle checkpoint semantics from a release or job packet
- do not make Discord import paths a requirement of core packages
