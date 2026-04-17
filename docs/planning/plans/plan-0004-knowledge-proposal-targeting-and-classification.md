---
id: plan-0004
label: Knowledge proposal targeting and classification
state: draft
summary: Implement precise page/section targeting, confidence-based classification,
  and high-confidence patch generation for knowledge proposals
spec_refs: []
request_refs: []
work_package_refs: []
standard_refs:
- standard-0006
---

# Plan: Knowledge Proposal Automation Upgrade (request-29)

## Context
Request-29 seeks to upgrade proposal system from passive triage to precise, actionable documentation maintenance. Spec-0011 defines the approach: context-aware targeting, confidence classification (actionable_high_confidence / review_only / no_op_transient), and patch action generation.

Current state:
- Proposal schema has `actions` field
- Patch infrastructure exists (patches.py with replace_section, append_section)
- Deduplication working
- Accept/reject/apply workflow in place

Gaps:
1. Page/section targeting broad (any page affected)
2. No confidence classification logic
3. No patch action generation for high-confidence proposals
4. Proposal volume high due to low-signal transients

## Task Breakdown

### Task 1: Implement targeting logic (event_scanner.py)
- Analyze drift items to identify affected_sections (durable: "Current state", "How to use", etc.)
- Use page_id refs + touched source paths to narrow target_page_id
- When multiple pages affected, split into separate proposals
- Output: target_page_id + affected_sections in proposal payload

### Task 2: Implement classification logic (event_scanner.py)
- Define classifiers:
  - actionable_high_confidence: narrow change + clear target + durable section stale
  - review_only: ambiguous or manual_stale
  - no_op_transient: build artifacts, non-docs, etc.
- Integrate into proposal generation
- Output: classification in proposal payload

### Task 3: Implement patch action generation (event_scanner.py)
- For actionable_high_confidence: generate replace_section or append_section actions
- Synthesize section body from drift context (source change, page state)
- Decide replace vs append based on drift type
- Integrate into proposal payload

### Task 4: Filter no-op transients (event_scanner.py)
- Prevent proposal file generation for no_op_transient classification
- Record as audit event instead
- Verify dedupe still works (don't lose audit trail)

### Task 5: Update proposal schema docs + tests
- Document unified schema: rationale (drift_items, suggested_steps) + actions
- Add tests for targeting, classification, patch generation
- Benchmark proposal volume before/after

### Task 6: Integrate with apply workflow (lifecycle.py)
- Ensure apply_proposal respects new actions field
- Verify patches.py apply_patch_file handles generated actions
- End-to-end test: generate high-confidence proposal → review → apply

## Implementation Order
1. Task 1 (targeting)
2. Task 2 (classification)
3. Task 4 (filter no-op) — cheap win, reduces volume early
4. Task 3 (patch generation)
5. Task 5 (tests + docs)
6. Task 6 (integration)

## Success Criteria
- Proposals include target_page_id and affected_sections
- Classification visible in proposal payloads
- High-confidence proposals generate patch actions
- No-op transients filtered → measurable volume drop
- All tests pass
- End-to-end workflow works: generate → review → apply
