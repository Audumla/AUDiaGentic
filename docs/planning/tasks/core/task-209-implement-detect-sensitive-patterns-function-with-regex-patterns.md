---
id: task-209
label: Implement detect_sensitive_patterns function with regex patterns
state: done
summary: Add detect_sensitive_patterns(body) with regex for AWS keys, API keys, passwords,
  bearer tokens; return warning messages
spec_ref: spec-12
request_refs: []
standard_refs:
- standard-5
- standard-6
---













---
id: task-212
label: Implement check_sensitive_data function with regex patterns
state: draft
summary: Add check_sensitive_data(id) function to tm_helper with regex for AWS keys, API keys, passwords, bearer tokens; return structured dict with warnings
spec_ref: spec-9
---

# Implementation

Add `check_sensitive_data(id_: str, root: Path | None = None)` function to `tools/planning/tm_helper.py`:

## Regex Patterns
```python
PATTERNS = {
    'aws_key': r'AKIA[0-9A-Z]{16}',
    'api_key': r'(?:api[_-]?key|apikey)[\s]*[=:]\s*["\']?[a-zA-Z0-9]{20,}["\']?',
    'password': r'(?:password|passwd|pwd)[\s]*[=:]\s*["\']?[^"\'\s]+["\']?',
    'bearer_token': r'Bearer\s+[a-zA-Z0-9\-._~+/]+=*',
}
```

## Function Signature
```python
def check_sensitive_data(
    id_: str, 
    root: Path | None = None
) -> dict[str, Any]:
    """Check planning item for sensitive data patterns.
    
    Args:
        id_: Planning item ID
        root: Optional project root
        
    Returns:
        {
            "id": "task-0112",
            "has_sensitive_data": bool,
            "warnings": list[str],
            "patterns_checked": list[str]
        }
    """
```

## Return Shape
- `id`: The item being checked
- `has_sensitive_data`: True if any patterns matched
- `warnings`: List of detected pattern types
- `patterns_checked`: List of pattern names checked

## Notes
- Body-only scanning (not frontmatter, attachments)
- Returns structured dict for easy MCP serialization
- Simple, no dependencies beyond re module

# Description

Implement the core detection function for sensitive data patterns. Add regex patterns for AWS keys, API keys, passwords, and bearer tokens. Function scans markdown body only and returns a structured dict indicating what was found.
