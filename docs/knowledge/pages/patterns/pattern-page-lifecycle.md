## Summary
The **Page Lifecycle Pattern** defines the standard lifecycle for knowledge pages from creation to archival. It ensures consistent page structure, metadata management, and clear transitions between states. This pattern applies to all page types in the knowledge vault.

## Current state
**Lifecycle States:**

```
scaffold → draft → active → stale → (update | archive)
```

**State Descriptions:**

| State | Description | Metadata |
|-------|-------------|----------|
| **scaffold** | Page template created, content not written | `status: draft` |
| **draft** | Content being written, not complete | `status: draft` |
| **active** | Complete and current | `status: active` |
| **stale** | Sources changed, needs review | `status: stale` |
| **archived** | Superseded, moved to archive | Moved to `data/archive/` |

**Page Structure:**
Each page has two files:
1. **Content**: `docs/knowledge/pages/<type>/<page-id>.md`
2. **Metadata**: `docs/knowledge/data/meta/<type>/<page-id>.meta.yml`

**Standard Sections:**
```markdown

## Summary
Brief overview (1-2 paragraphs).

## Current state
Detailed description of how it works now.

## How to use
Instructions for humans or agents.

## Sync notes
How and when this page should be updated.

## References
Links to related documentation.
```

**Metadata Schema:**
```yaml
id: unique-page-id
title: Human Readable Title
type: system|guide|tool|pattern|decision|glossary_term|runbook
status: draft|active|stale
summary: Brief description
owners:
  - team-or-person
tags:
  - tag1
  - tag2
related:
  - other-page-id
updated_at: 2026-04-14
```

**Transitions:**

1. **scaffold → draft**: Content writer starts filling in sections
2. **draft → active**: Content complete, reviewed, marked `status: active`
3. **active → stale**: Event adapter marks page stale when sources change
4. **stale → active**: Content updated after review
5. **stale → archive**: Page superseded, moved to `archive/`

## How to use
**Creating a New Page:**

```bash

## Scaffold a new page
python -m src.audiagentic.knowledge.cli --root . scaffold-page my-new-page system "My New Page" "Brief description" --owner team
```

**Writing Content:**
1. Edit the markdown file
2. Fill in all standard sections
3. Update `status: draft` to `status: active` when complete
4. Add `updated_at` date

**Responding to Stale Status:**
1. Check `docs/knowledge/data/proposals/` for sync proposals
2. Review what changed in source materials
3. Update page content
4. Change `status: stale` to `status: active`
5. Update `updated_at` date

**Archiving a Page:**
1. Create replacement page if needed
2. Move old page to `docs/knowledge/data/archive/`
3. Update metadata: `status: archived`
4. Add note about superseding page

**Best Practices:**
- Always include all standard sections
- Keep summaries concise
- Use present tense for current state
- List sync sources explicitly
- Update metadata when content changes
- Link related pages

## Sync notes
This page documents the page lifecycle pattern itself. It should be refreshed when:
- Page template changes
- Metadata schema is modified
- Lifecycle states are added or removed
- Standard sections are updated

**Sources:**
- `docs/knowledge/templates/page-template.md` - Page template
- `src/audiagentic/knowledge/importers.py` - Scaffolding logic
- Page metadata schema

**Sync frequency:** On page template or schema changes

## References
- [Knowledge System](../systems/system-knowledge.md)
- [Glossary: Current State](../glossary/glossary-current-state.md)
- Page template: `docs/knowledge/templates/page-template.md`
