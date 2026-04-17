---
id: task-0265
label: Implement planning audit and repair CLI command
state: done
summary: Create planning audit CLI command to detect and repair inconsistent hierarchies
  with fix logging
spec_ref: spec-020
request_refs:
- request-18
standard_refs:
- standard-0005
- standard-0006
---










# Description

Implement `audiagentic planning audit` CLI command to detect and repair inconsistent planning hierarchies. This task owns scanning for state inconsistencies, reporting findings, and optionally auto-fixing by re-running propagation logic.

**Commands:**
```bash
audiagentic planning audit
  # Scan and report inconsistent hierarchies
  
audiagentic planning audit --fix
  # Scan, report, and auto-fix inconsistencies
  
audiagentic planning audit --verbose
  # Show detailed propagation log analysis
```

**Inconsistency detection:**
- WP state doesn't match children (e.g., WP=ready but task=in_progress)
- Plan state doesn't match WPs
- Spec state doesn't match plans
- Missing propagation log entries

**Auto-fix:**
- Re-run propagation logic for inconsistent items
- Log all fixes applied
- Idempotent: safe to run multiple times

# Acceptance Criteria

- `audit` command scans all planning items for inconsistent hierarchies
- `audit` reports items where parent state doesn't match children
- `audit --fix` automatically repairs inconsistencies by re-running propagation
- `audit --verbose` shows detailed propagation log analysis
- All fixes logged to `propagation_log.json` with `fixed_by_audit: true` flag
- Command is idempotent (safe to run multiple times)
- Unit tests cover: inconsistency detection, auto-fix, idempotency
- Integration test covers: crash simulation → audit → repair
- Smoke test proves audit command executes without errors

# Notes
Depends on: task-0251 (propagation engine), task-0252 (config). This task is CLI and audit logic only.

Assessment on 2026-04-17: audit/repair remains useful but does not replace fixing the root propagation defect tracked in `task-0006`. The observed `draft -> done` failure came from live propagation during state changes, not only from stale persisted hierarchies.

Implemented on 2026-04-17: added `tm audit` / `tm audit --fix` in `tools/planning/tm.py`, backed by existing propagation validation/healing logic and audit log writes to `.audiagentic/planning/meta/propagation_log.json` with `fixed_by_audit: true`. Added integration coverage in `tests/integration/planning/test_tm_audit.py` for report and repair flows. Verified with `pytest tests/integration/planning/test_tm_audit.py -q` -> 2 passed.
