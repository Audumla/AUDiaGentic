---
id: task-0003
label: Remove hook_config_file from config.py
state: cancelled
summary: Delete hook_config_file property and references from KnowledgeConfig
request_refs:
- request-21
standard_refs:
- standard-0005
- standard-0006
---



The hook_config_file property in KnowledgeConfig should be removed. This property points to 'sync/hooks.yml' which is part of the legacy hooks system. All references to this property in config.py need to be removed.

# Notes

Cancelled on 2026-04-17 as redundant placeholder work under superseded `request-21`. Current knowledge architecture still intentionally uses hook-based sync alongside event-driven behavior.
