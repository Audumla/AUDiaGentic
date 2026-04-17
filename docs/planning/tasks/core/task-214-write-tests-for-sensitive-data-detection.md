---
id: task-214
label: Write tests for sensitive data detection
state: done
summary: Add tests for AWS key, API key, password detection; confirm non-blocking
  behavior; test false positive edge cases
spec_ref: spec-9
request_refs: []
standard_refs:
- standard-5
- standard-6
---







---
id: task-214
label: Write tests for sensitive data detection
state: draft
summary: Add tests for detection function, MCP tool, warning structure, and edge cases
spec_ref: spec-9
---

# Test Coverage

## Unit Tests: check_sensitive_data()
- Detects AWS key pattern in body
- Detects API key pattern
- Detects password pattern
- Detects bearer token pattern
- Returns has_sensitive_data=true when patterns found
- Returns has_sensitive_data=false when clean
- Returns empty warnings list when clean
- Returns populated warnings list when issues found
- Handles items with None/empty body gracefully
- Returns correct pattern names in warnings list

## Integration Tests: tm_check_sensitive_data MCP Tool
- Tool callable via MCP JSON-RPC
- Returns dict with correct structure
- `id` field matches input
- `has_sensitive_data` is boolean
- `warnings` is list
- `patterns_checked` contains all pattern names

## Edge Cases
- Item with no body returns no warnings
- Item with mixed content (clean + suspicious) returns only suspicious warnings
- False positives (normal text with "password" word) logged for awareness
- Very large bodies process without timeout
- Non-existent item ID handled gracefully

## Notes
- Tests should NOT modify planning items
- Tests are non-blocking (detection is advisory)
- Include examples of each pattern type in test fixtures

# Description

Write comprehensive tests for the detection function and MCP tool. Cover pattern detection, return structure, edge cases, and false positives.
