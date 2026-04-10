# PKT-PRV-061 — Config-driven canonical tag names

**Phase:** Phase 4.4.1
**Status:** VERIFIED
**Owner:** Infrastructure

## Objective

Remove all hardcoded canonical tag name literals from Python source and replace them with
values loaded from `prompt-syntax.yaml` via helpers in `prompt_syntax.py`.

## Problem

Tag names (`"review"`, `"audit"`, `"check-in-prep"`, `"implement"`) were hardcoded in
`prompt_parser.py` and `prompt_launch.py`. Any rename or prefix change required hunting
down every usage site. This packet makes the tag grammar fully config-managed.

## Scope

- `prompt_syntax.py` — `DEFAULT_PROMPT_SYNTAX` extended with `canonical-tags`,
  `no-body-required-tags`, `review-tag`, `implement-tag`
- `prompt_syntax.py` — helpers `load_canonical_tags()`, `load_no_body_required_tags()`,
  `load_review_tag()`
- `prompt_parser.py` — all hardcoded tag literals replaced with config-loaded values:
  - `_split_tag_and_provider` accepts `allowed_tags` parameter
  - `_infer_target_from_id` accepts `review_tag` parameter
  - body-check uses `no_body_required_tags` set
  - generic tag fallback uses `implement_tag` from config
- `prompt_launch.py` — `review_tag` loaded from config, not hardcoded
- `.audiagentic/prompt-syntax.yaml` — `canonical-tags` list, `no-body-required-tags`,
  `review-tag`, `implement-tag` fields added

## Dependencies

- None (self-contained refactor)

## Acceptance criteria

- [x] `prompt_syntax.py` exposes `load_canonical_tags()`, `load_no_body_required_tags()`,
  `load_review_tag()`
- [x] `prompt_parser.py` contains no hardcoded canonical tag name strings
- [x] `prompt_launch.py` contains no hardcoded `"review"` tag literal
- [x] All existing integration tests pass unchanged
- [x] Unit tests cover alias resolution via `load_canonical_tags` with custom syntax dict

## Notes

- Backward-compat aliases (`plan`, `review`, `r`, etc.) remain in `prompt-syntax.yaml`
  so existing prompts continue to work unchanged
- The module-level `ALLOWED_TAGS` fallback is intentionally kept for call sites that
  have no project root available; it calls `load_canonical_tags({})` so it still
  reflects the canonical defaults
