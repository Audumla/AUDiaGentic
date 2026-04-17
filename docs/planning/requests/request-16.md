---
id: request-16
label: Planning Module Critical Fixes
state: closed
summary: 'Fix critical bugs in planning module: create_with_content() drops standard_refs,
  update_content() has dead code, val_mgr.py has duplicated validation logic'
source: Planning Module Critical Review (2026-04-14)
guidance: standard
current_understanding: 'Two comprehensive reviews identified critical bugs and architectural
  issues. Immediate fixes needed: create_with_content() silently drops standard_refs
  for specs/tasks/plans/WPs, update_content() section mode has duplicated regex blocks
  with inconsistent formatting, val_mgr.py runs section validation twice and iterates
  items 6+ times. Also tracked: api.py God Object (911 lines), no rollback on multi-step
  ops, lazy claims expiry, unbounded event log growth.'
open_questions:
- Should we fix bugs first or refactor api.py first?
- What's the priority order for the 7 critical issues?
- Do we need rollback before fixing the bugs?
meta:
  request_type: feature
standard_refs:
- standard-1
spec_refs:
- spec-17
- spec-18
---






# Understanding

Two comprehensive reviews identified critical bugs and architectural issues. Immediate fixes needed: create_with_content() silently drops standard_refs for specs/tasks/plans/WPs, update_content() section mode has duplicated regex blocks with inconsistent formatting, val_mgr.py runs section validation twice and iterates items 6+ times. Also tracked: api.py God Object (911 lines), no rollback on multi-step ops, lazy claims expiry, unbounded event log growth.

# Open Questions

- Should we fix bugs first or refactor api.py first?
- What's the priority order for the 7 critical issues?
- Do we need rollback before fixing the bugs?

# Problem



# Desired Outcome



# Constraints


# Notes
Closed on 2026-04-17 after assessment. The critical planning fixes tracked here were implemented through the linked tasks and work package; only a duplicate placeholder spec remained to clean up.
