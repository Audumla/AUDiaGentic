# Planning Request Source Field Convention

## Definition

The `source` field identifies the **agent or user who created the planning request**. It must be a creator identifier, not a process description or workflow context.

## Valid Examples

- `claude` — Created by Claude agent
- `codex` — Created by Codex agent
- `user@example.com` — Created by a specific user
- `cline` — Created by Cline agent
- `gemini` — Created by Gemini agent

## Invalid Examples (Anti-patterns)

❌ `extracted-from-request-0004` — Process description, not creator  
❌ `discovered-during-mcp-tool-review` — Context/workflow, not creator  
❌ `consolidation` — Process name, not creator  
❌ `created-by-automation` — Too vague, not a specific identifier

## Why This Matters

The `source` field is required (as of request-0010) for **auditability and traceability**. It must answer the question: "Who made this request?" not "How was this request created?" or "What process led to this?"

## Implementation Enforcement

- **Caller awareness** is the primary enforcement mechanism — this convention must be understood by anyone creating requests
- The `source` field is required at the API level (no null values allowed)
- Schema validation ensures it's a non-empty string
- Pattern-based or enum validation cannot work because new agents/users may be added

## When Creating Requests

If you're using the planning API or MCP tools to create a request, ensure the `source` parameter is:
1. A specific identifier (agent name, username, email, etc.)
2. NOT a description of how the request came about
3. NOT a reference to another request or process

Example correct usage:
```
tm_new_request(
    label="Add feature X",
    summary="Implement X for efficiency",
    source="claude",  # ✓ Agent identifier
    ...
)
```

Example incorrect usage:
```
tm_new_request(
    label="Add feature X",
    summary="Implement X for efficiency",
    source="discovered-during-review",  # ✗ Process, not creator
    ...
)
```
