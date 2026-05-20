# knowledge/

AUDiaGentic knowledge component - deterministic knowledge state management with event-driven sync.

## Purpose

Provides a fully-implemented knowledge vault system for managing current-state project documentation:
- Markdown-based knowledge pages with metadata sidecars
- Drift detection between sources and documentation
- Event-driven sync from planning and runtime events
- Lexical search across knowledge pages
- Optional LLM integration (deterministic-first design)
- CLI and MCP interfaces

## Status

**Fully implemented and operational.**

Integrated into AUDiaGentic on 2026-04-14 via [request-0032](../../docs/planning/requests/request-0032.md).

**Current capabilities:**
- 23 modules (~3,267 lines of code)
- Knowledge vault at `docs/knowledge/`
- 14 seed pages created and populated
- Event bridge to planning system (2132+ events processed)
- CLI commands for all operations
- MCP server for agent integration

## Architecture

```
knowledge/
  __init__.py          - Module exports
  actions.py           - Deterministic action handlers
  bootstrap.py         - Vault initialization
  capability.py        - Contract validation
  cli.py               - Command-line interface
  config.py            - Configuration loading
  diffing.py           - Change detection
  events.py            - Event processing (TODO: split)
  importers.py         - Page scaffolding
  llm.py               - Optional LLM integration
  markdown_io.py       - Markdown parsing
  mcp_server.py        - MCP tool server (moved to tools/mcp/audiagentic-knowledge/)
  models.py            - Data models
  navigation.py        - Navigation routing
  patches.py           - Patch application
  registry.py          - Registry loading
  runtime_defaults.py  - Default configurations
  runtime_data/        - YAML profiles and contracts
  search.py            - Lexical search (TODO: enhance)
  status.py            - Status reporting
  sync.py              - Drift detection
  validation.py        - Vault validation
  utils.py             - Utilities
```

## Configuration

- Main config: `.audiagentic/knowledge/config.yml`
- Event adapters: `docs/knowledge/events/adapters.yml`
- Registries: `docs/knowledge/registries/` (actions, importers, execution, llm)
- Runtime defaults: `runtime_data/` (capability profiles, host profiles, contracts)

## Usage

**CLI:**
```bash
# Validate vault
python -m src.audiagentic.knowledge.cli --root . validate

# Scan for drift
python -m src.audiagentic.knowledge.cli --root . scan-drift

# Process events
python -m src.audiagentic.knowledge.cli --root . process-events

# Search pages
python -m src.audiagentic.knowledge.cli --root . search --query "planning"

# View status
python -m src.audiagentic.knowledge.cli --root . status
```

**MCP:**
```bash
# Via launcher (recommended)
python tools/mcp/audiagentic-knowledge/launch_audiagentic_knowledge_mcp.py

# Or directly
python tools/mcp/audiagentic-knowledge/mcp_server.py --root .
```

## Known Issues

See [Critical Review](#critical-review-findings) below for known gaps and planned improvements.

### Critical Review Findings

**Reviewed:** 2026-04-14

**Status:** Integration complete, improvements planned

| Issue | Status | Action |
|-------|--------|--------|
| Zero tests across 3,267 lines | ⚠️ Known | Tests planned for events.py, sync.py, validation.py |
| events.py has too many responsibilities (413 lines) | ⚠️ Known | Split planned: scanning → normalization → dispatch → state |
| Lexical search is naive (51 lines) | ⚠️ Known | Enhancement planned: stemming, fuzzy matching, stopwords |
| LLM job state unstructured (llm-jobs.yml) | ⚠️ Known | Lifecycle management planned |
| 27 MCP tools is too many | ⚠️ Known | Consolidation planned: 4-5 top-level tools |
| Sync proposals have no lifecycle | ⚠️ Known | Accept/reject/merge states planned |
| config.py path resolution | ✅ Verified | Uses relative paths from config, not hardcoded |
| Bootstrap idempotency | ✅ Verified | Skips existing files unless `--force` |

**Applied Fixes:**
- ✅ Updated README to reflect "fully implemented" status
- ✅ Verified bootstrap idempotency (skips existing files)
- ✅ Verified config.py uses relative paths from configuration

**Planned Improvements:**
1. Add unit tests for events.py, sync.py, validation.py
2. Split events.py into separate modules
3. Enhance search.py with stemming and fuzzy matching
4. Add lifecycle management for LLM jobs
5. Consolidate MCP tools into 4-5 top-level tools
6. Add proposal lifecycle (accept/reject/merge)

## Must not own

- Planning workflows (those stay in planning/)
- Provider-specific execution
- Runtime lifecycle
- Release management

## Must support

- Optional enablement per project
- Multiple backend implementations
- Project-local content without shared system code ownership

## Integration

- **Planning bridge**: Event adapter watches `.audiagentic/planning/events/events.jsonl`
- **Knowledge vault**: `docs/knowledge/` with pages, meta, proposals, registries
- **Event processing**: 2132+ planning events processed at integration

## References

- [Knowledge System Documentation](../../docs/knowledge/pages/systems/system-knowledge.md)
- [Integration Request](../../docs/planning/requests/request-0032.md)
- [Integration Plan](../../docs/planning/plans/plan-0017-knowledge-component-integration-plan.md)
