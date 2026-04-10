# PKT-PRV-062 — Surface regeneration facade (`regenerate_tag_surfaces.py`)

**Phase:** Phase 4.4.1
**Status:** READY_FOR_REVIEW
**Owner:** Infrastructure

## Objective

Refactor existing `tools/regenerate_tag_surfaces.py` into a shared facade/orchestrator that reads
canonical provider-function definitions from `.audiagentic/skills/` and dispatches
provider-specific rendering to provider-owned surface renderer definitions, keeping all
provider outputs in sync with zero manual editing.

## Problem

Provider skill or instruction surfaces (`.claude/skills/`, `.agents/skills/`,
`.clinerules/skills/`, `.gemini/commands/`, and future provider surfaces) are currently
hand-authored separately. This causes:

- Content drift between providers over time
- Manual work every time a tag is renamed or a new provider is added
- No way to verify that provider files match the canonical source (CI cannot catch drift)

Current reality before this refactor:
- `tools/regenerate_tag_surfaces.py` already existed
- it hardcoded provider rendering logic directly in the tool
- it did not read canonical source from `.audiagentic/skills/`
- it generated legacy unprefixed duplicate skill folders
- it did not generate the missing Cline/Gemini provider surfaces or stamp managed headers

## Scope

The shared facade must:

1. Read canonical provider-function definitions from `.audiagentic/skills/<tag>/skill.md`
2. For each provider listed in config:
   - load that provider's renderer definition from provider-owned code/config
   - let the provider renderer decide output format, path layout, and provider-specific additions
   - stamp output files with a `MANAGED_BY_AUDIAGENTIC` comment header
3. Support `--dry-run` (print diffs, write nothing)
4. Support `--check` (exit non-zero if any file would change — usable as a CI gate)
5. Support `--project-root` (default: `.`)
6. Remove legacy duplicate-surface generation from the shared tool rather than continuing to
   emit both canonical `ag-*` and unprefixed folders

### Architecture rule

The facade must not hardcode provider rendering details directly into one growing script.
Provider-specific rendering belongs to provider-owned renderer definitions/modules.

### Provider renderer architecture

Each provider owns its renderer details. The shared facade is responsible only for:

- reading canonical provider-function source files
- loading provider renderer definitions
- dispatching canonical source into those renderers
- applying common diff/check/write/header behavior

Renderer contract requirements:

- renderer logic must live in provider-owned code or config, not as provider-specific helper
  functions embedded in the shared facade
- each renderer must accept the canonical tag/function id, the canonical source payload, and
  provider/path config, then return rendered provider output
- the facade must use an explicit registry/discovery seam so adding a new provider does not
  require embedding that provider's formatting rules directly into the tool
- renderer implementations are responsible for format differences such as YAML frontmatter,
  flat markdown, or provider-specific wrapper text

The exact module path can be finalized during implementation, but it must remain provider-owned
under the provider layer rather than becoming a new monolithic formatting section inside
`tools/regenerate_tag_surfaces.py`.

### Canonical source

`.audiagentic/skills/<tag>/skill.md` — behavioral content only, no provider-specific
formatting. This is the canonical generic provider-function source, not a provider-ready file
format. Fields:

```

The shared facade must not treat `.audiagentic/skills/` as a reusable generic skill file
format for providers. Each provider renderer must produce its own provider-owned output shape
from the canonical source so providers can diverge safely in path layout, metadata, wrapper
text, and other surface-specific requirements.
---
name: ag-review
description: <one-line description>
---

# <tag> skill

Trigger:
- ...

Do:
- ...

Do not:
- ...
```

## Dependencies

- PKT-PRV-061 VERIFIED (canonical tag names in config)
- PKT-PRV-070 VERIFIED (canonical provider-function source files created)

## Files to create or update

- `tools/regenerate_tag_surfaces.py`
- `.audiagentic/skills/<tag>/skill.md` × 5 (owned by PKT-PRV-070)
- `docs/specifications/architecture/50_Template_Installation_and_Managed_Surface_Contract.md`
  — reference this tool in the `required-managed` section

## Acceptance criteria

- `python tools/regenerate_tag_surfaces.py --project-root . --check` exits 0 when all
  provider files match canonical source
- `--dry-run` prints per-file diffs and exits 0
- Running the tool is idempotent (repeated runs produce no changes)
- Adding a new canonical function/tag to `.audiagentic/skills/` and re-running regenerates
  all provider surfaces without manual editing in the shared facade
- Adding a new provider does not require embedding that provider's formatting rules into the
  shared facade; the provider contributes its own renderer definition/module
- Provider renderers are successfully invoked by the tool; the shared facade does not contain
  provider-specific rendering implementations as its long-term architecture
- legacy unprefixed duplicate skill folders are not generated by the refactored tool
- CI can run `--check` to catch drift

## Notes

- Provider files generated by this tool are `required-managed` — they must not be
  hand-edited. This is enforced by the `MANAGED_BY_AUDIAGENTIC` header and documented
  in spec 50 (PKT-PRV-063)
- Refactor scope explicitly includes removing hardcoded legacy duplicate generation from the
  shared tool. Deletion of already-existing legacy folders still happens as a deliberate
  migration step owned by PKT-PRV-070.
- Current repo state after implementation: the tool now reads `.audiagentic/skills/`, uses
  provider-owned renderer modules under `src/audiagentic/execution/providers/surfaces/`,
  generates Cline/Gemini/opencode provider surfaces, and stamps managed headers. Review
  should focus on renderer boundaries, generated output fidelity, and idempotence.
