---
id: spec-14
label: Precise knowledge proposal targeting and classification
state: draft
summary: Define context-aware page/section targeting, confidence-based classification,
  and actionable patch generation for knowledge proposals so proposal volume drops
  while usefulness rises
request_refs:
- request-26
task_refs: []
standard_refs:
- standard-0006
- standard-0005
---







# Purpose

Upgrade knowledge proposal system from broad triage queue to precise, actionable documentation maintenance.

# Scope

- Context-aware page/section targeting from refs, touched surfaces, event metadata
- Confidence-based classification: high-confidence actionable vs low-confidence review-only vs no-op transient
- Unified proposal schema: rationale + executable patch actions
- High-confidence proposal generation of durable section edits (replace_section, append_section)
- Reduced proposal volume via better classification and transient filtering
- Maintain safe, auditable behavior and deduplication

Out of scope:
- New proposal action types beyond current patch.py coverage
- Changing knowledge page schema
- LLM-based proposal drafting enhancements (separate from this spec)

# Requirements

## Targeting

Proposals should identify target page and affected sections precisely:

- Use knowledge page references (page_id, touched source paths) to narrow target
- From drift analysis, identify which durable sections need updates (e.g., "Current state", "How to use")
- When multiple pages affected, generate separate proposals (one per page)
- Include target_page_id and affected_sections in proposal payload

## Classification

Classify each proposal into one of:

1. **actionable_high_confidence**: Generate executable patch actions (replace_section, append_section)
   - Trigger: narrow source change, clear page match, durable section is stale
   - Action: generate patch actions for proposal review

2. **review_only**: Require manual review, no auto-patch
   - Trigger: ambiguous targeting, multiple possible sections, or manual_stale flag
   - Action: generate sync_review proposal with suggested_steps only

3. **no_op_transient**: Skip proposal generation
   - Trigger: transient status (e.g., build artifact changed, non-doc drift)
   - Action: record as audit event, do not create pending proposal file

## Patch Generation

For high-confidence proposals, generate executable patch actions:

- Analyze drift and determine if target section should be replaced or appended
- Generate replace_section action with new content synthesized from drift context
- Generate append_section action for incremental updates (e.g., adding new feature to How to use)
- Include action in proposal payload for review and conditional apply

## Proposal Volume Reduction

Better classification should reduce pending proposals:

- No-op transients filtered out early → fewer stale files
- Precise targeting → fewer "might apply to these 5 pages" ambiguity proposals
- High-confidence actionable proposals → fewer review_only backlog

# Acceptance Criteria

1. Proposals include target_page_id and affected_sections in payload
2. Classification logic is clearly defined and testable (actionable_high_confidence, review_only, no_op_transient)
3. High-confidence proposals generate replace_section or append_section actions
4. Unified schema unifies rationale (drift_items, suggested_steps) and executable actions
5. Proposal volume is measurably lower than before (benchmark before/after proposal file counts)
6. Deduplication and safe audit trails remain intact
7. Tests cover targeting, classification, patch generation, and no-op filtering

# Constraints

- Preserve proposal provenance to source events and drift
- Keep review-required for any ambiguous targeting or low-confidence cases
- Do not auto-apply without proposal being accepted (existing apply_proposal workflow)
- Stay compatible with patches.py apply_patch_file action execution
