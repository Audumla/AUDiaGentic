# AUDiaGentic E2E Build Pack v14

This pack extends the v13 end-to-end staged build plan with a **core build-status system** and a clearer **Phase 0–2 execution reference**.

The purpose of this revision is to make implementation activity easier to coordinate across multiple agents and developers without duplicated work or uncertainty about current build state.

## What changed in v14

- adds a **single build status and work registry** that must be updated for all implementation activity
- adds a **start-here guide** for any new developer or agent joining the project
- adds a **Phase 0–2 readiness and execution reference** consolidating packet inventories, strict execution order, and phase gates
- updates the implementation index, kickoff checklist, and packet execution rules so build-status tracking is mandatory rather than optional

## Start here

1. `docs/implementation/31_Build_Status_and_Work_Registry.md`
2. `docs/implementation/32_New_Agent_or_Developer_Start_Here.md`
3. `docs/implementation/00_Implementation_Index.md`
4. `docs/implementation/01_Master_Implementation_Roadmap.md`
5. `docs/implementation/02_Phase_Gates_and_Exit_Criteria.md`
6. `docs/implementation/20_Packet_Dependency_Graph.md`
7. `docs/implementation/33_Phase_0_1_2_Readiness_and_Execution_Reference.md`

## Working rule for all implementation activity

No agent or developer should begin packet or module work until:

- the packet or module is located in the build-status registry
- dependencies are shown as satisfied
- the work item is explicitly claimed in the registry
- the owner has read the packet build sheet and relevant contracts

The build-status registry is the live operational starting point for all work.

## Validation and Maintenance

### Docker Test Path

Use the existing Docker base image as the normal test path. Do not rebuild test
images for routine validation unless the image inputs changed.

Normal path:

```bash
docker run --rm \
  -v "${PWD}:/app" \
  -w /app \
  -e AUDIAGENTIC_DOCKER_TESTS=1 \
  -e AUDIAGENTIC_REPO_ROOT=/app \
  audia-test-base:latest \
  bash -lc "python3 -m pip install --no-cache-dir --break-system-packages -e . pytest pytest-asyncio mcp==1.27.0 && pytest tests/integration/release tests/e2e/release -q"
```

Rebuild only when one of these changed:

- `Dockerfile.test-base`
- `Dockerfile.test`
- `Dockerfile.release-test`
- image-level package/tool bootstrap requirements
- the local image is missing or known-bad

Use `Dockerfile.release-test` only when validating the wheel-installed release
path or package-data bundling. It is not the default recheck path.

### Planning Document Integrity

Before merging planning changes or after bulk operations, run:

```bash
# Check for broken references in planning documents
python tools/checks/repair_broken_refs.py
```

This tool checks metadata fields (YAML frontmatter) for broken references. Body text references are intentionally excluded as they are often historical/documentation. See `docs/planning/docs/BROKEN_REFERENCE_POLICY.md` for details.

### Other Validation Tools

```bash
# Validate all planning objects
python tools/planning/tm.py validate

# Check ID format and uniqueness
python tools/validation/validate_ids.py

# Verify schema validity
python tools/validation/validate_schemas.py
```

See `tools/README.md` for a complete list of available tools.
