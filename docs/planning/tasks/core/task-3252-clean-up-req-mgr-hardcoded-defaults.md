---
id: task-3252
label: Clean up req_mgr hardcoded defaults
state: done
summary: Remove fallback hardcoded methods from RequestMgr
spec_ref: spec-29
request_refs: []
standard_refs:
- standard-5
- standard-6
---




## Description

Clean up `req_mgr.py` to fully use config for defaults, removing fallback hardcoded methods.

## Current State

`req_mgr.py` has partial config usage but still has hardcoded fallbacks:
- `_default_open_questions(profile)` at lines 21-38 - hardcoded questions per profile
- `_default_understanding(summary, profile)` at lines 40-45 - hardcoded understanding text

These are used as final fallback when config doesn't provide values, but config SHOULD always provide values now.

## Required Changes

1. Remove `_default_open_questions()` method
2. Remove `_default_understanding()` method
3. Update create() to require config to provide defaults (no fallback)
4. Ensure profiles.yaml has complete defaults for all profiles
5. Ensure guidance_levels in profiles.yaml has complete defaults

## Acceptance Criteria

- `_default_open_questions()` method removed
- `_default_understanding()` method removed
- req_mgr.py fully relies on config for defaults
- profiles.yaml has complete defaults for all profiles (feature, issue, fix, enhancement)
- guidance_levels has complete defaults (light, standard, deep)
- No hardcoded strings remain in req_mgr.py
