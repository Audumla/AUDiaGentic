## Summary
The AUDiaGentic CLI provides command-line interfaces for the knowledge component and core system operations. It enables artifact management, state transitions, validation, search, event processing, and job control operations.

## Current state
**Knowledge CLI** (`src/audiagentic/knowledge/cli.py`):
- Validation: verify vault integrity
- Sync operations: scan drift, process events, apply proposals
- Search: lexical search across pages
- Question answering: deterministic-first QA over knowledge
- Scaffolding: create new pages
- Status: view vault health and statistics
- Bootstrap: initialize knowledge vault
- Actions: run deterministic actions
- Navigation: goal-based page navigation
- Index maintenance: maintain and validate index pages

**Main CLI** (`src/audiagentic/channels/cli/main.py`):
- Job control: manage execution jobs
- Prompt launch: trigger workflow jobs
- Prompt trigger bridge: normalize and route tagged prompts
- Session input: manage session state
- Release bootstrap: initialize release system
- Lifecycle stub: runtime lifecycle operations
- Provider status: check model provider status
- Refresh model catalog: update model registry

**Command Patterns:**
```bash
## Knowledge commands
python -m src.audiagentic.knowledge.cli --root . <command> [options]

## Main CLI commands
python -m src.audiagentic.channels.cli.main <command> [options]
```

## How to use
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
python -m src.audiagentic.knowledge.cli --root . generate-sync-proposals
python -m src.audiagentic.knowledge.cli --root . apply-proposals

## Search and query
python -m src.audiagentic.knowledge.cli --root . search --query "planning system" --limit 10
python -m src.audiagentic.knowledge.cli --root . get-page --page-id system-planning

## Question answering
python -m src.audiagentic.knowledge.cli --root . answer-question "How do I create a task?" --limit 8

## Draft sync proposals
python -m src.audiagentic.knowledge.cli --root . draft-sync-proposal --page-id system-planning

## Navigation
python -m src.audiagentic.knowledge.cli --root . navigate "find task templates" --limit 5

## Scaffolding
python -m src.audiagentic.knowledge.cli --root . scaffold-page my-page system "My Page" "Page summary" --owner core-team

## Bootstrap
python -m src.audiagentic.knowledge.cli --root . bootstrap --target . --knowledge-root docs/knowledge --capability-profile deterministic-minimal

## Registry operations
python -m src.audiagentic.knowledge.cli --root . list-actions
python -m src.audiagentic.knowledge.cli --root . run-action mark_stale_and_generate_sync_proposal --arguments '{"page_id": "my-page"}'
python -m src.audiagentic.knowledge.cli --root . show-action-registry
python -m src.audiagentic.knowledge.cli --root . show-importer-registry
python -m src.audiagentic.knowledge.cli --root . show-llm-registry
python -m src.audiagentic.knowledge.cli --root . show-event-adapters
python -m src.audiagentic.knowledge.cli --root . show-navigation

## LLM profile jobs
python -m src.audiagentic.knowledge.cli --root . list-profiles
python -m src.audiagentic.knowledge.cli --root . submit-profile-job summarize --payload '{"text": "..."}'
python -m src.audiagentic.knowledge.cli --root . get-job-status job-123
python -m src.audiagentic.knowledge.cli --root . get-job-result job-123

## Stale page management
python -m src.audiagentic.knowledge.cli --root . mark-stale page-1 page-2
python -m src.audiagentic.knowledge.cli --root . clear-stale page-1
python -m src.audiagentic.knowledge.cli --root . record-sync page-1

## Source evaluation
python -m src.audiagentic.knowledge.cli --root . evaluate-source docs/planning/tasks/task-0001.md

## Patch application
python -m src.audiagentic.knowledge.cli --root . apply-patch docs/knowledge/proposals/20260417T032700Z-system-planning.yml

## Index maintenance
python -m src.audiagentic.knowledge.cli --root . maintain-index
python -m src.audiagentic.knowledge.cli --root . validate-index
python -m src.audiagentic.knowledge.cli --root . refresh-index
```

**Main CLI Commands:**

```bash
## Job control
python -m src.audiagentic.channels.cli.main job-control --operation list
python -m src.audiagentic.channels.cli.main job-control --operation status --job-id job-123

## Prompt launch
python -m src.audiagentic.channels.cli.main prompt-launch --prompt "@ag-plan Review the system"

## Prompt trigger bridge
python -m src.audiagentic.channels.cli.main prompt-trigger-bridge --raw-prompt "@ag-review provider=codex"

## Session input management
python -m src.audiagentic.channels.cli.main session-input --operation add --details '{"event": "..."}'

## Release bootstrap
python -m src.audiagentic.channels.cli.main release-bootstrap --target .

## Provider status
python -m src.audiagentic.channels.cli.main providers-status

## Refresh model catalog
python -m src.audiagentic.channels.cli.main refresh-model-catalog
```

**JSON Output:**
Add `--json` flag to any command for machine-parseable output:
```bash
python -m src.audiagentic.knowledge.cli --root . status --json
```

**Common Patterns:**

```bash
## Validate before committing
python -m src.audiagentic.knowledge.cli --root . validate
python -m src.audiagentic.knowledge.cli --root . scan-drift

## Process new events and sync
python -m src.audiagentic.knowledge.cli --root . scan-events
python -m src.audiagentic.knowledge.cli --root . process-events
python -m src.audiagentic.knowledge.cli --root . generate-sync-proposals
python -m src.audiagentic.knowledge.cli --root . apply-proposals

## Search and navigate knowledge
python -m src.audiagentic.knowledge.cli --root . search --query "planning system"
python -m src.audiagentic.knowledge.cli --root . navigate "how to create tasks"

## Answer questions from knowledge base
python -m src.audiagentic.knowledge.cli --root . answer-question "What are the planning artifact types?"
```

## Sync notes
This page should be refreshed when:
- New CLI commands are added
- Command signatures change
- New flags or options are introduced
- Deprecated commands are removed

**Sources:**
- `src/audiagentic/knowledge/cli.py` - Knowledge CLI
- `src/audiagentic/channels/cli/main.py` - Main CLI
- Argument parser definitions in each CLI module

**Sync frequency:** On CLI API changes

## References
- [Planning System](../systems/system-planning.md)
- [Knowledge System](../systems/system-knowledge.md)
- [Using the Planning System](../guides/guide-using-planning.md)
- [MCP Server](./tool-mcp.md)
