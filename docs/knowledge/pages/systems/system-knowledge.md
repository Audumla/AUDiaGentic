## Summary
The AUDiaGentic knowledge component provides deterministic knowledge state management with event-driven updates. It functions as an **access layer** that maintains current-state project documentation in a structured vault, ensures index pages stay synchronized with content, and provides controlled access to knowledge through CLI and MCP interfaces. The component is config-driven with no hardcoded values.

**Key principle**: The Knowledge API is an access layer, not a managed service. Its role is to:
- Provide controlled read/write access to knowledge pages
- Ensure index pages stay synchronized with underlying data
- Maintain consistency between sources and documentation
- Handle drift detection and sync operations

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
- **State** (`state/`): Sync state, event state, snapshots
- **Archive** (`archive/`): Applied proposals and archived pages
- **Import** (`import/manifests/`): Import manifests for seeding
- **Templates** (`templates/`): Page scaffolding templates

**Configuration** (`.audiagentic/knowledge/`):
- **Config** (`config.yml`): Main configuration file
- **Events** (`events/`): Event adapters and handlers configuration
- **Registries** (`registries/`): Action, importer, execution, and LLM registries
- **Sync** (`sync/`): Sync hooks configuration
- **Navigation** (`navigation/`): Navigation routes configuration
- **Profiles** (`profiles/`): Capability and host profiles

**Core Capabilities:**
- **Index Maintenance**: Automatic index page generation and link validation
- **Sync**: Detect drift between sources and knowledge pages
- **Events**: Process file changes and event streams (e.g., planning events)
- **Actions**: Deterministic operations (scan, scaffold, search, validate)
- **Import**: Seed pages from manifests
- **Validation**: Verify vault integrity and page compliance
- **Search**: Lexical search across pages with weighted scoring

**Event Integration:**
- Planning events bridge: `.audiagentic/planning/events/events.jsonl` → knowledge sync
- Event adapters configured in `.audiagentic/knowledge/events/adapters.yml`
- Event handlers configured in `.audiagentic/knowledge/events/handlers.yml`
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
- Event adapters: `.audiagentic/knowledge/events/adapters.yml`
- Event handlers: `.audiagentic/knowledge/events/handlers.yml`
- Registries: `.audiagentic/knowledge/registries/` (actions, importers, execution, llm)
- Sync hooks: `.audiagentic/knowledge/sync/hooks.yml`
- Navigation: `.audiagentic/knowledge/navigation/routes.yml`
- Capability profiles: `deterministic-minimal`, `mcp-stdio`
- Runtime defaults in `src/audiagentic/knowledge/runtime_data/`

**Interfaces:**
- CLI: `python -m src.audiagentic.knowledge.cli --root . <command>`
- MCP: Model Context Protocol server for agent integration

**Access Layer Operations:**
- **Index Maintenance**: Automatic generation and validation of index pages
  - `maintain-index`: Update all index pages based on current content
  - `validate-index`: Check that all index links point to valid pages
  - `refresh-index`: Maintain indexes and validate links in one operation
- **Controlled Access**: All read/write operations go through the API layer
  - Pages are loaded with metadata validation
  - Index pages are automatically kept in sync
  - Cross-references are validated on demand

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

## Maintain index pages
audiagentic-knowledge --root . maintain-index

## Validate index links
audiagentic-knowledge --root . validate-index

## Refresh all indexes
audiagentic-knowledge --root . refresh-index
```

**Event-Driven Sync:**
1. Configure event adapters in `.audiagentic/knowledge/events/adapters.yml`
2. Configure event handlers in `.audiagentic/knowledge/events/handlers.yml`
3. Events are scanned and processed automatically
4. Sync proposals generated in `docs/knowledge/proposals/`
5. Deterministic proposals auto-applied; review_only proposals require manual review
6. Applied proposals archived in `docs/knowledge/archive/`
7. Index pages are automatically maintained after sync operations

**Page Lifecycle:**
1. Scaffold page with required sections
2. Populate content following current-state conventions
3. Metadata auto-generated in sidecar file
4. Events may mark pages stale when sources change (filtered by payload)
5. Deterministic proposals auto-applied; review_only proposals queued for manual review
6. Index pages updated automatically when pages are created or modified

## Sync notes
This page should be refreshed when:
- Knowledge component API changes
- New page types are added
- Event adapter schema changes
- CLI commands are modified
- Index maintenance operations are added or modified

**Sources:**
- `src/audiagentic/knowledge/` - Core implementation
- `src/audiagentic/knowledge/index_maintenance.py` - Index maintenance layer
- `.audiagentic/knowledge/config.yml` - Main configuration
- `.audiagentic/knowledge/registries/` - Action and importer registries
- `.audiagentic/knowledge/events/` - Event adapters and handlers
- `.audiagentic/knowledge/sync/` - Sync hooks
- `.audiagentic/knowledge/navigation/` - Navigation routes

**Sync frequency:** On knowledge component changes

## References
- [Planning System](./system-planning.md)
- [Execution System](./system-execution.md)
- [Runtime System](./system-runtime.md)
- [Interoperability System](./system-interoperability.md)
- [Release System](./system-release.md)
- [CLI Tool](../tools/tool-cli.md)
- [MCP Server](../tools/tool-mcp.md)
- Event adapters: `docs/knowledge/events/adapters.yml`
