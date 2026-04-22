---
id: task-271
label: Add validation for session_input --details-json
state: completed
summary: Validate event data structure in CLI arguments
request_refs:
- request-19
standard_refs:
- standard-5
- standard-6
---









## Completed Work

Added validation for `session_input --details-json` argument in `channels/cli/main.py`.

### Changes Made:

1. **Replaced direct `json.loads` with `_load_json_argument`**:
   - Now uses the validated JSON loading function
   - Consistent error handling with other JSON arguments

2. **Added `_validate_session_input_details` function**:
   - Validates details is a JSON object
   - Type validation for known fields:
     - `kind`: must be string
     - `label`: must be string
     - `summary`: must be string
     - `metadata`: must be object
     - `attachments`: must be array
   - Comprehensive docstring with valid structure example

3. **Added validation call in session-input command**:
   - Validates details before processing
   - Raises ValueError with specific field error if validation fails

## Standards Compliance
- **standard-0005**: Schema validation for CLI arguments
- **standard-0008**: Comprehensive documentation and type hints

## Testing
Validation now properly handles:
- Non-object JSON (ValueError: details must be a JSON object)
- Invalid kind type (ValueError: details.kind must be a string)
- Invalid label type (ValueError: details.label must be a string)
- Invalid summary type (ValueError: details.summary must be a string)
- Invalid metadata type (ValueError: details.metadata must be an object)
- Invalid attachments type (ValueError: details.attachments must be an array)
- None/missing details (skipped validation, passes None to tool)
