# Release Notes

## v0.4.1

### Configuration
- Reduce routine CI latency while preserving full background coverage and adding release artifact verification.

### Fixes
- Prevent snapshot cancellation from leaving observation running and retain CI diagnostic artifacts.
- Prevent concurrent startup-lock claims from losing gateway session updates.

### Testing
- Allow full CI test inventory without weakening empty-execution failure checks.
- Make CI source-provenance checks reliable inside browser containers.
