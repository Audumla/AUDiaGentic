---
id: task-1
label: Remove hooks.py from knowledge component
state: cancelled
summary: Delete src/audiagentic/knowledge/hooks.py after migrating to event-driven
  architecture
request_refs:
- request-21
standard_refs:
- standard-5
- standard-6
---









Remove the legacy hooks.py file from the knowledge component. This file contains hooks evaluation logic that filters events based on path and content patterns. This logic should be replaced with event-based filtering in the event adapters. The hooks system is legacy code that should have been migrated to events (similar to task-0263 for planning).

# Notes

Cancelled on 2026-04-17 as redundant placeholder work under superseded `request-21`. Current knowledge architecture still intentionally uses hook-based sync alongside event-driven behavior.
