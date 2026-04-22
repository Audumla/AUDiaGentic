---
id: task-2
label: Remove hooks.yml and update CLI
state: cancelled
summary: Delete docs/knowledge/sync/hooks.yml and remove CLI hooks commands
request_refs:
- request-21
standard_refs:
- standard-5
- standard-6
---









The hooks.yml file defines hook eligibility rules that should be removed. Also, the CLI has hooks-related commands (`_print_hooks()` and `_print_evaluate()`) that need to be removed from cli.py. The config.py also references `hook_config_file` which needs to be removed.

# Notes

Cancelled on 2026-04-17 as redundant placeholder work under superseded `request-21`. Current knowledge architecture still intentionally uses hook-based sync alongside event-driven behavior.
