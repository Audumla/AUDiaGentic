# Phase 0 Kickoff Checklist

Use this checklist before starting any Phase 0 packet work.

## Required reading
- `31_Build_Status_and_Work_Registry.md`
- `32_New_Agent_or_Developer_Start_Here.md`
- `01_Master_Implementation_Roadmap.md`
- `02_Phase_Gates_and_Exit_Criteria.md`
- `06_Phase_0_Build_Book.md`
- `20_Packet_Dependency_Graph.md`

## Team kickoff actions
- [ ] confirm CI/CD tool choice for Phase 0 work
- [ ] confirm Python version and test framework
- [ ] assign initial Phase 0 packet owners
- [ ] open `31_Build_Status_and_Work_Registry.md` and record packet claims
- [ ] confirm branch/worktree naming convention
- [ ] confirm review/update discipline for build-status registry

## Before claiming a packet
- [ ] packet is `READY_TO_START` in the registry
- [ ] all dependencies are `VERIFIED`
- [ ] ownership boundaries are understood
- [ ] relevant spec docs are read
- [ ] packet build sheet is read end-to-end

## Phase 0 packets to populate in build-status registry
- PKT-FND-001
- PKT-FND-002
- PKT-FND-003
- PKT-FND-004
- PKT-FND-005
- PKT-FND-006
- PKT-FND-007

## Phase 0 completion evidence
- [ ] schema validator runs in CI
- [ ] naming validator runs in CI
- [ ] lifecycle CLI stub emits deterministic output
- [ ] fixtures validate or fail as expected
- [ ] packet dependency validator runs in CI
- [ ] build-status registry is updated to reflect merged and verified packet states
- [ ] Phase 0 gate is recorded as complete before Phase 1 work starts
