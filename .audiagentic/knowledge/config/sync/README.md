# Knowledge Sync Hooks

This directory contains configuration files for source eligibility hooks that determine whether files should trigger knowledge sync actions.

## Files

- `hooks.yml`: Configuration file defining eligibility rules for source files

## Hook Evaluation Flow

1. Load all hooks from `hooks.yml`
2. Filter hooks by `applies_to` path patterns
3. Evaluate eligibility rules for each matching hook
4. If any hook marks source as ineligible, skip processing
5. If all hooks pass or no hooks match, source is eligible

## Eligibility Rule Types

- `reject_when_path_contains`: Reject if path contains any of these strings
- `reject_when_content_contains`: Reject if file content contains any of these strings
- `allow_when_content_contains_any`: Require at least one of these strings in content

## Actions

- `generate_sync_proposal`: Create a sync proposal for review
- `mark_stale`: Mark affected pages as stale without generating proposal
- `none`: Just evaluate, take no action

## Configuration Format

```yaml
hooks:
  - id: <unique-hook-id>
    kind: <hook-type>
    applies_to:
      - <path-pattern>
    eligibility:
      reject_when_path_contains:
        - <path-token>
      reject_when_content_contains:
        - <content-token>
      allow_when_content_contains_any:
        - <allow-marker>
    action: <action-name>
    action_args:
      <arg-name>: <value>
    note: <documentation>
```

## Standard Reference

This configuration follows standard-0013 (Event subscription configuration standard) for config-driven behavior.
