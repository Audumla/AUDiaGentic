# Current Release

## Changes

### code-fix
- [chg_20261024_011637_prevent-snapshot-cancellation_1883] Prevent snapshot cancellation from leaving observation running and retain CI diagnostic artifacts.
- [chg_20261024_015045_prevent-concurrent-startup-loc_8327] Prevent concurrent startup-lock claims from losing gateway session updates.

### config
- [chg_20261024_010041_reduce-routine-ci-latency-whil_8472] Reduce routine CI latency while preserving full background coverage and adding release artifact verification.

### tests
- [chg_20261024_011148_allow-full-ci-test-inventory-w_6766] Allow full CI test inventory without weakening empty-execution failure checks.
- [chg_20261024_012426_make-ci-source-provenance-chec_6124] Make CI source-provenance checks reliable inside browser containers.
