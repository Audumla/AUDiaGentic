# Current Release

## Changes

### code-fix
- [chg_20261023_021624_repair-ci-contract-validation_7517] Repair CI contract validation and clean-room build/test assumptions without weakening production contracts.
- [chg_20261023_022035_prevent-ci-plugin-startup-erro_6279] Prevent CI plugin startup errors and false Pi RPC EOF failures during active long streaming turns.
- [chg_20261023_023912_repair-ci-dependency-and-stale_2929] Repair CI dependency and stale integration-contract failures while preserving fail-closed gateway routing.
- [chg_20261023_031451_prevent-bounded-journal-compac_4697] Prevent bounded journal compaction from repeatedly blocking active streaming sessions and stop duplicate CI runs consuming runner capacity.

### feature
- [chg_20261023_040315_rotate-gateway-traces-daily-c_7921] Rotate gateway traces daily, compress closed segments and expire eligible raw traces after five days without deleting results or protected recovery evidence.

### tests
- [chg_20261023_024359_bring-planning-and-pi-isolatio_2751] Bring planning and Pi isolation test fixtures and generated capability reference in line with current contracts.
- [chg_20261023_030830_repair-linux-ci-portability-s_1888] Repair Linux CI portability, startup prerequisites, deterministic crash/lease tests, and planning integrity while retaining diagnostic evidence.
- [chg_20261023_031007_make-real-model-smoke-prompts_5115] Make real-model smoke prompts and model choice consistent with the working RPC baseline and preserve Windows CLI diagnostics.
- [chg_20261023_044332_repair-ci-test-composition-for_6729] Repair CI test composition for persistent GPT sessions and bound real-model Pi smoke behavior without skipping checks.
