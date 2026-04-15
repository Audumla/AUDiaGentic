## Summary
The AUDiaGentic CLI provides command-line interfaces for both the planning system and knowledge component. It enables artifact management, state transitions, validation, search, and event processing operations.

## Current state
**Planning CLI** (`src/audiagentic/planning/cli.py`):
- Artifact creation: requests, specs, plans, tasks, work packages
- State management: transition tasks between states
- Query operations: list, show, search artifacts
- Maintenance: validation, reconciliation, indexing

**Knowledge CLI** (`src/audiagentic/knowledge/cli.py`):
- Validation: verify vault integrity
- Sync operations: scan drift, process events
- Search: lexical search across pages
- Scaffolding: create new pages
- Status: view vault health and statistics
- Bootstrap: initialize knowledge vault

**Command Patterns:**
```bash

## Planning commands
python -m src.audiagentic.planning.cli <command> [options]

## Knowledge commands
python -m src.audiagentic.knowledge.cli --root . <command> [options]
```

## How to use
**Planning Commands:**

```bash

## Create artifacts
python -m src.audiagentic.planning.cli new-request --label "Label" --summary "Summary"
python -m src.audiagentic.planning.cli new-spec --label "Label" --summary "Summary"
python -m src.audiagentic.planning.cli new-plan --label "Label" --summary "Summary" --spec spec-XXXX
python -m src.audiagentic.planning.cli new-task --label "Label" --summary "Summary" --spec spec-XXXX

## Query artifacts
python -m src.audiagentic.planning.cli show --id task-XXXX
python -m src.audiagentic.planning.cli list --kind task
python -m src.audiagentic.planning.cli next-tasks --state ready --domain core

## Manage state
python -m src.audiagentic.planning.cli state --id task-XXXX --new-state in_progress --reason "Starting work"

## Maintenance
python -m src.audiagentic.planning.cli validate
python -m src.audiagentic.planning.cli reconcile
python -m src.audiagentic.planning.cli index
```

**Knowledge Commands:**

```bash

## Health and status
python -m src.audiagentic.knowledge.cli --root . doctor
python -m src.audiagentic.knowledge.cli --root . status
python -m src.audiagentic.knowledge.cli --root . validate

## Sync operations
python -m src.audiagentic.knowledge.cli --root . scan-drift
python -m src.audiagentic.knowledge.cli --root . scan-events
python -m src.audiagentic.knowledge.cli --root . process-events
python -m src.audiagentic.knowledge.cli --root . record-event-baseline

## Search and query
python -m src.audiagentic.knowledge.cli --root . search --query "planning system" --limit 10
python -m src.audiagentic.knowledge.cli --root . get-page --page-id system-planning

## Scaffolding
python -m src.audiagentic.knowledge.cli --root . scaffold \
  --id my-page \
  --type system \
  --title "My Page" \
  --summary "Page summary" \
  --owners ["team"]

## Bootstrap
python -m src.audiagentic.knowledge.cli --root . bootstrap \
  --target . \
  --knowledge-root docs/knowledge \
  --capability-profile deterministic-minimal
```

**JSON Output:**
Add `--json` flag to any command for machine-parseable output:
```bash
python -m src.audiagentic.knowledge.cli --root . status --json
```

**Common Patterns:**

```bash

## Find and claim a ready task
TASK=$(python -m src.audiagentic.planning.cli next-tasks --state ready | head -1)
python -m src.audiagentic.planning.cli state --id $TASK --new-state in_progress

## Validate before committing
python -m src.audiagentic.planning.cli validate
python -m src.audiagentic.knowledge.cli --root . validate

## Process new events
python -m src.audiagentic.knowledge.cli --root . scan-events
python -m src.audiagentic.knowledge.cli --root . process-events
```

## Sync notes
This page should be refreshed when:
- New CLI commands are added
- Command signatures change
- New flags or options are introduced
- Deprecated commands are removed

**Sources:**
- `src/audiagentic/planning/cli.py` - Planning CLI
- `src/audiagentic/knowledge/cli.py` - Knowledge CLI
- Argument parser definitions in each CLI module

**Sync frequency:** On CLI API changes

## References
- [Planning System](../systems/system-planning.md)
- [Knowledge System](../systems/system-knowledge.md)
- [Using the Planning System](../guides/guide-using-planning.md)
- [MCP Server](./tool-mcp.md)
