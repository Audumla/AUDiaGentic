## Request Source Field Semantics

The `source` field on planning requests must identify the **creator** (agent or user), not describe the process.

### Rules

- `source` MUST be a creator identifier (e.g., `claude`, `codex`, `user@example.com`)
- `source` MUST NOT be a process description or workflow context
- `source` is required (non-null) on all requests

### Valid Examples

- `claude` — Created by Claude agent
- `codex` — Created by Codex agent
- `user@example.com` — Created by a specific user
- `cline`, `gemini`, `opencode` — Other agents

### Invalid Examples (Anti-patterns)

- ❌ `extracted-from-request-0004` — Process description
- ❌ `discovered-during-mcp-tool-review` — Context/workflow
- ❌ `consolidation` — Process name
- ❌ `created-by-automation` — Too vague

### Enforcement

- **Caller awareness** is the primary enforcement mechanism
- Schema validation ensures it's a non-empty string
- Pattern/enum validation cannot work (unbounded set of creators)
- Docstrings and API descriptions clarify the requirement
- See `docs/references/planning/REQUEST_SOURCE_FIELD.md` for detailed guidance
