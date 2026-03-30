# Target Codebase Tree

```text
src/
  audiagentic/
    cli/
      main.py
    contracts/
      canonical_ids.py
      schemas.py
      validation.py
      glossary.py
    lifecycle/
      detector.py
      manifest.py
      checkpoints.py
      fresh_install.py
      update_dispatch.py
      cutover.py
      uninstall.py
      migration.py
      workflow_management.py
    release/
      fragments.py
      sync.py
      current_summary.py
      audit.py
      finalize.py
      release_please.py
      history_import.py
    jobs/
      records.py
      store.py
      state_machine.py
      profiles.py
      packet_runner.py
      stages.py
      approvals.py
      release_bridge.py
    providers/
      registry.py
      selection.py
      health.py
      catalog.py
      models.py
      adapters/
        local_openai.py
        claude.py
        codex.py
        gemini.py
        copilot.py
        continue_.py
        cline.py
    server/
      service_boundary.py
    overlay/
      discord/
        subscriber.py
        release_publish.py
        approval_publish.py
        notices.py
        models.py
tools/
  validate_ids.py
  validate_schemas.py
  seed_example_project.py
  lifecycle_stub.py
  refresh_model_catalog.py
tests/
  fixtures/
  unit/
  integration/
  e2e/
```

## Rules

- All production code lives under `src/audiagentic/`.
- All standalone utility entry points live under `tools/` but should call library code under `src/audiagentic/`.
- Tests must mirror the production module structure where practical.
- Packets must not create alternative parallel module trees.
- When a packet needs a new module outside this tree, it must update this file before code is written.


## v12 additions

The following files/directories are now part of the target baseline:

```text
docs/specifications/architecture/20_Error_Envelope_and_Error_Codes.md
docs/implementation/19_CI_CD_and_Testing_Infrastructure.md
docs/implementation/20_Packet_Dependency_Graph.md
docs/implementation/21_Destructive_Test_Sandbox.md
docs/implementation/22_Secret_Management.md
docs/implementation/23_Release_Please_Invocation.md
docs/implementation/24_Cross_Phase_Integration_Testing.md
docs/implementation/25_Change_Control_and_Document_Update_Rules.md
tools/validate_packet_dependencies.py
```
