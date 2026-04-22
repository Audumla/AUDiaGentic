---
id: spec-12
label: Cursory sensitive data detection in planning validation (v1)
state: ready
summary: Add lightweight regex-based detection of common secrets (AWS keys, API keys,
  passwords) in planning item body content; emit as non-blocking warnings during validation
request_refs:
- request-5
task_refs:
- ref: task-230
  seq: 1000
- ref: task-231
  seq: 1001
- ref: task-232
  seq: 1002
standard_refs:
- standard-6
- standard-5
---









# Purpose

Add lightweight, cursory detection of common sensitive patterns in planning item body content. Implement as a standalone MCP tool that agents can call explicitly. This is v1: simple, fast, can be extended later.

# Scope (v1: Intentionally Minimal & Standalone)

Detect only:
- AWS Access Keys (AKIA pattern)
- API Keys (generic patterns: `api_key=`, `apikey:`, `API_KEY=`)
- Passwords (basic patterns: `password=`, `passwd=`, `pwd=`)
- Common tokens (Bearer tokens in markdown)

Check only:
- Markdown body content (item.body)

Implement as:
- New standalone MCP tool: `tm_check_sensitive_data(id: str)` 
- Returns warnings list for explicit item checks
- Agents call it when they want to scan (opt-in)
- Does NOT integrate into validation (keeps API stable)

Do NOT include in v1:
- Frontmatter checking
- Attachment/resource scanning
- Allow-listing or overrides
- Sophisticated entropy analysis
- Custom detection rules
- Configuration options
- Blocking validation

# Requirements

## 1. Detection Patterns

Simple regex patterns for:
```python
PATTERNS = {
    'aws_key': r'AKIA[0-9A-Z]{16}',
    'api_key': r'(?:api[_-]?key|apikey)[\s]*[=:]\s*["\']?[a-zA-Z0-9]{20,}["\']?',
    'password': r'(?:password|passwd|pwd)[\s]*[=:]\s*["\']?[^"\'\s]+["\']?',
    'bearer_token': r'Bearer\s+[a-zA-Z0-9\-._~+/]+=*',
}
```

## 2. Detection Function

```python
def check_sensitive_data(id_: str, root: Path | None = None) -> dict[str, Any]:
    """Scan a planning item for sensitive patterns in body.
    
    Returns:
    {
        "id": "task-0112",
        "has_sensitive_data": false,
        "warnings": [],
        "patterns_checked": ["aws_key", "api_key", "password", "bearer_token"]
    }
    
    Or if sensitive data found:
    {
        "id": "task-0112",
        "has_sensitive_data": true,
        "warnings": [
            "Possible AWS access key detected in body",
            "Possible API key detected in body"
        ],
        "patterns_checked": ["aws_key", "api_key", "password", "bearer_token"]
    }
    """
    item = api.show(id_)
    body = api._find(id_).body
    
    warnings = []
    for name, pattern in PATTERNS.items():
        if re.search(pattern, body, re.IGNORECASE):
            warnings.append(f"Possible {name.replace('_', ' ')} detected in body")
    
    return {
        "id": id_,
        "has_sensitive_data": len(warnings) > 0,
        "warnings": warnings,
        "patterns_checked": list(PATTERNS.keys()),
    }
```

## 3. MCP Tool: tm_check_sensitive_data

New standalone tool:
```python
@mcp.tool(description="Check a planning item for sensitive data patterns (AWS keys, API keys, passwords, tokens) in body content")
def tm_check_sensitive_data(id: str) -> dict[str, Any]:
    return tm.check_sensitive_data(id)
```

**Usage:**
```python
# Agent explicitly checks an item
result = tm_check_sensitive_data("task-0112")
if result["has_sensitive_data"]:
    print(f"⚠️  {id}: {result['warnings']}")
```

## 4. Helper Function: tm_helper.check_sensitive_data

```python
def check_sensitive_data(id_: str, root: Path | None = None) -> dict[str, Any]:
    """Check planning item for sensitive data patterns."""
    # Implementation as above
```

## 5. Testing

Basic tests:
- Detects AWS key pattern in body
- Detects API key pattern
- Detects password pattern
- Detects bearer token
- Does NOT trigger on false positives in normal text
- Returns correct warning messages
- Returns has_sensitive_data=false when clean
- Returns empty warnings list when clean
- Handles missing items gracefully

# Constraints

- **Performance:** Regex patterns should be fast; no heavy computation
- **Isolation:** Detection is standalone, not integrated into validation
- **False positives:** Accept some in v1 (can be refined later)
- **False negatives:** OK to miss some patterns (cursory by design)
- **No persistence:** Warnings are returned but not stored/tracked
- **No side effects:** Detection does not modify planning items
- **No validation integration:** Does not integrate into tm_validate() flow

# What's Explicitly NOT in v1

- ❌ Allow-listing of credentials
- ❌ Frontmatter/metadata checking
- ❌ Attachment scanning
- ❌ Configuration/custom rules
- ❌ Integration into validation
- ❌ Blocking validation
- ❌ Audit trail
- ❌ Entropy-based detection
- ❌ NLP or advanced analysis

# Acceptance Criteria

- [x] Design complete (lightweight, standalone)
- [ ] `check_sensitive_data(id)` function implemented in tm_helper
- [ ] `tm_check_sensitive_data(id)` MCP tool exposed
- [ ] AWS key, API key, password, bearer token patterns detected
- [ ] Returns structured dict with has_sensitive_data boolean and warnings list
- [ ] Tests confirm detection works and returns correct structure
- [ ] No changes to validation API or tm_validate() behavior
- [ ] Cursory approach documented; v2 expansion noted
- [ ] Tool is opt-in (agents call explicitly)

# Notes

This is intentionally standalone: regex patterns, body-only, advisory warnings via explicit tool call. The goal is to catch obvious accidental leaks (copy-paste mishaps) without heavyweight infrastructure or API disruption. Agents opt-in by calling tm_check_sensitive_data when they want to scan.

v2 expansion options (not in scope):
- Integration into validation workflow
- Allow-listing of known test credentials
- Frontmatter and attachment scanning
- Integration with external secret scanning tools
- Configurable pattern sets
- Audit trail for detected issues
