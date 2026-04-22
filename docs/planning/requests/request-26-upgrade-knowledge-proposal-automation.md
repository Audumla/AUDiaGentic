---
id: request-26
label: Upgrade knowledge proposal automation
state: captured
summary: Improve proposal targeting, classification, unified schema, and high-confidence
  patch generation so knowledge proposals become precise actionable documentation
  updates
source: codex
guidance: standard
current_understanding: Initial intake captured; requirements are understood well enough
  to proceed.
open_questions:
- What exact outcome is required?
- What constraints or non-goals apply?
- How will success be verified?
standard_refs:
- standard-1
spec_refs:
- spec-0006
- spec-0007
- spec-0008
- spec-0009
- spec-0010
- spec-14
---













# Understanding

Knowledge proposal workflow now dedupes, cleans up, supports accept/reject/apply, and can generate safe executable patch actions for accepted review proposals.

Current gap: proposal system still acts mostly as triage. High-confidence proposals usually append review notes to `Sync notes` rather than generating durable section updates. Targeting and classification remain broad and rule-based, so proposal volume stays higher than value.

# Problem

Proposal workflow needs feature upgrade from passive review queue to precise, actionable documentation maintenance.

Current shortcomings:
1. Page and section targeting are broad rather than context-precise.
2. Proposal classification is heuristic for `review_update` vs `reject_no_doc_change`.
3. Review guidance and executable patch actions are split concepts.
4. High-confidence proposals do not yet synthesize real updates for durable sections like `Current state` and `How to use`.
5. Many proposals still require manual interpretation even when source change is narrow and traceable.

# Desired Outcome

Upgrade proposal generation and application.

Observable outcomes:
1. Better page/section targeting from refs, touched surfaces, and event context.
2. Low-signal transient events produce audit/no-op outcomes instead of full pending proposals.
3. Proposal schema unifies rationale and executable actions.
4. High-confidence proposals can generate `replace_section` / `append_section` edits for durable sections, not only `Sync notes` traces.
5. Proposal review surface clearly explains why proposal exists, what changed, and what exact update is recommended.
6. Proposal volume drops while usefulness and auto-apply value rise.

# Constraints

- Keep safe, auditable behavior first.
- Preserve proposal provenance to source events and drift.
- Do not reintroduce duplicate proposal generation.
- Stay compatible with existing knowledge patch pipeline.
- Keep review-only path for low-confidence cases.

# Verification Expectations

1. High-confidence proposals generate actionable section edits.
2. No-op/transient events produce fewer pending proposal files.
3. Unified schema stays readable and executable through CLI workflow.
4. Duplicate prevention remains intact.
5. Tests cover targeting, classification, patch generation, and apply flow.
