## Summary
The AUDiaGentic knowledge component provides deterministic knowledge state management with event-driven updates. It maintains current-state project documentation in a structured vault, syncs from source materials and runtime events, and supports both CLI and MCP interfaces. The component is config-driven with no hardcoded values.

## Current state
The knowledge component consists of:

**Vault Structure** (`docs/knowledge/`):
- **Pages** (`pages/`): Current-state documentation organized by type
  - `systems/` - System architecture and operational state
  - `guides/` - How-to guides and workflows
  - `tools/` - Tool references and CLI documentation
  - `patterns/` - Design patterns and best practices
  - `decisions/` - Architecture decision records
  - `glossary/` - Terminology definitions
  - `runbooks/` - Operational procedures
- **Metadata** (`meta/`): Sidecar YAML files mirroring page structure
- **Proposals** (`proposals/`): Sync proposals generated from events
- **Registries** (`registries/`): Action, importer, execution, and LLM configs
- **Events** (`events/`): Event adapter configurations
- **State** (`state/`): Sync state, event state, snapshots

**Core Capabilities:**
- **Sync**: Detect drift between sources and knowledge pages
- **Events**: Process file changes and event streams (e.g., planning events)
- **Actions**: Deterministic operations (scan, scaffold, search, validate)
- **Import**: Seed pages from manifests
- **Validation**: Verify vault integrity and page compliance
- **Search**: Lexical search across pages with weighted scoring

**Event Integration:**
- Planning events bridge: `.audiagentic/planning/events/events.jsonl` → knowledge sync
- Event adapters configured in `docs/knowledge/events/adapters.yml`
- 2607+ planning events tracked, 7346 event records processed (baseline recorded)
- Event adapters active: `planning-state-changes`, `planning-task-completed-legacy`, `wp-review-trigger`
- Affected pages: system-planning, system-knowledge, guide-using-planning, tool-cli, tool-mcp, pattern-event-bridge, pattern-page-lifecycle
- Actions: 
  - `mark_stale_and_generate_sync_proposal` - pages marked stale and sync proposals generated automatically
  - `create_agent_review_task` - creates automated review tasks for work-packages entering review state
- Auto-apply: Deterministic proposals (proposal_mode: deterministic) are automatically applied without manual review
- Payload filters: Only events with `payload.new_state` in [done, verified] trigger updates
- Agent review: Work-packages entering 'review' state trigger automated review task creation (task-review-{wp_id})

**Configuration:**
- Main config: `.audiagentic/knowledge/config.yml`
- Capability profiles: `deterministic-minimal`, `mcp-stdio`
- Runtime defaults in `src/audiagentic/knowledge/runtime_data/`

**Interfaces:**
- CLI: `python -m src.audiagentic.knowledge.cli --root . <command>`
- MCP: Model Context Protocol server for agent integration

## How to use
**CLI Commands:**
```bash

## Validate vault
audiagentic-knowledge --root . validate

## Scan for drift
audiagentic-knowledge --root . scan-drift

## Process events
audiagentic-knowledge --root . process-events

## Apply sync proposals
audiagentic-knowledge --root . apply-proposals

## Search pages
audiagentic-knowledge --root . search --query "planning system"

## Scaffold new page
audiagentic-knowledge --root . scaffold --id my-page --type system --title "My Page"

## Check health
audiagentic-knowledge --root . doctor

## View status
audiagentic-knowledge --root . status
```

**Event-Driven Sync:**
1. Configure event adapters in `docs/knowledge/events/adapters.yml`
2. Events are scanned and processed automatically
3. Sync proposals generated in `docs/knowledge/proposals/`
4. Deterministic proposals auto-applied; review_only proposals require manual review
5. Applied proposals archived in `docs/knowledge/archive/`

**Page Lifecycle:**
1. Scaffold page with required sections
2. Populate content following current-state conventions
3. Metadata auto-generated in sidecar file
4. Events may mark pages stale when sources change (filtered by payload)
5. Deterministic proposals auto-applied; review_only proposals queued for manual review

## Sync notes
This page should be refreshed when:
- Knowledge component API changes
- New page types are added
- Event adapter schema changes
- CLI commands are modified

**Sources:**
- `src/audiagentic/knowledge/` - Core implementation
- `.audiagentic/knowledge/config.yml` - Configuration
- `docs/knowledge/registries/` - Action and importer registries

**Sync frequency:** On knowledge component changes

## References
- [Knowledge Component Source](https://github.com/audiagentic/knowledge)
- [Critical Review: Architecture](../docs/CRITICAL_REVIEW.md)
- [Code Review: Fixes Applied](../docs/CODE_REVIEW_FIXES.md)
- [Improvements Specification](../../../docs/planning/specifications/spec-0052-knowledge-component-improvements-specification.md)
- [Event Adapters](../events/adapters.yml)
- [CLI Tool](../tools/tool-cli.md)
