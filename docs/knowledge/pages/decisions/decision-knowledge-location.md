---
id: decision-knowledge-location
title: Knowledge Vault Location
type: decision
status: current
summary: Decision to place the knowledge vault under docs/knowledge/ instead of repository root, organizing all documentation under a single docs/ directory
owners:
- core-team
updated_at: '2026-04-15'
tags:
- decision
- organization
- structure
related:
- system-knowledge
---

## Summary
Decision to place the knowledge vault under `docs/knowledge/` instead of at the repository root. This organizes all documentation under a single `docs/` directory, improving clarity and maintainability.

## Current state
**Decision Date:** 2026-04-14

**Status:** Implemented

**Context:**
The knowledge component was initially bootstrapped with the vault at the repository root (`knowledge/`). This created a flat structure where `knowledge/`, `docs/planning/`, `src/`, and `tools/` were all siblings.

**Decision:**
Move the knowledge vault to `docs/knowledge/` to:
1. Group all documentation under `docs/`
2. Clarify that knowledge vault is documentation, not source code
3. Align with common repository conventions
4. Improve discoverability for new contributors

**Rationale:**
- **Clarity**: `docs/` clearly indicates documentation content
- **Organization**: Planning docs and knowledge docs are now siblings
- **Convention**: Matches common open-source repository structures
- **Separation**: Clearer boundary between docs and source code

**Implementation:**
1. Updated `.audiagentic/knowledge/config.yml`: `knowledge_root: docs/knowledge`
2. Moved `knowledge/` directory to `docs/knowledge/`
3. Verified all CLI commands work with new path
4. Updated knowledge pages to reflect new location

**Consequences:**
- ✅ Improved repository organization
- ✅ Better alignment with contributor expectations
- ✅ Clearer docs vs code separation
- ⚠️ Existing links to `knowledge/` need updating
- ⚠️ CI/CD paths may need adjustment

**Alternatives Considered:**
1. **Keep at root**: Simpler paths, but less organized
2. **`documentation/knowledge/`**: More explicit, but non-standard
3. **`docs/vault/`**: Different naming, but "knowledge" is more descriptive

## How to use
This decision is implemented. The knowledge vault is now at `docs/knowledge/`.

**Reference the correct path:**
```bash
# Knowledge vault
docs/knowledge/pages/
docs/knowledge/meta/
docs/knowledge/proposals/

# Configuration
.audiagentic/knowledge/config.yml
```

**Update references:**
- Search for `knowledge/` at repo root
- Update to `docs/knowledge/`
- Check CI/CD configurations
- Update any external documentation

## Sync notes
This is an architecture decision record (ADR). It should be updated if:
- The decision is reversed
- Additional context becomes relevant
- New alternatives are evaluated

**Sources:**
- `.audiagentic/knowledge/config.yml` - Current configuration
- Repository structure

**Sync frequency:** If decision changes

## References
- [Knowledge System](../systems/system-knowledge.md)
- Configuration: `.audiagentic/knowledge/config.yml`
- Knowledge vault: `docs/knowledge/`
