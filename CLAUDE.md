<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

# CLAUDE.md

This repository uses AUDiaGentic workflow jobs.

## Prompt tag doctrine

- Parse only the first non-empty line for the workflow tag.
- Keep tag semantics identical to the shared AUDiaGentic launch contract.
- Do not invent provider-specific alternate tags.
- Preserve raw prompt text in provenance metadata.
- Keep provenance visible: provider id, surface, and session id should survive normalization.

<!-- AUDIAGENTIC:BEGIN agent-ledger/process -->
## Agent ledger process

For release-affecting work, follow AUDiaGentic agent ledger process.
- Check release ledger state before changing release notes, changelog fragments, or release workflow files.
- Keep release artifacts and job records synchronized with implementation and review outcomes.
- Add or update the release ledger fragment when behavior, public workflow, or generated release output changes.
- Do not bypass ledger updates by editing generated release outputs only.
<!-- AUDIAGENTIC:END agent-ledger/process -->

<!-- AUDIAGENTIC:BEGIN agent-ledger/write-instruction -->
## Ledger write instruction

After completing substantive implementation work, record a change event to the ledger
using the ag-ledger MCP tool (record_change_event).
Do not skip this step — the ledger is the authoritative record for release tracking.
<!-- AUDIAGENTIC:END agent-ledger/write-instruction -->

<!-- AUDIAGENTIC:BEGIN source-control/doctrine -->
## Source control doctrine

Do not invoke git or GitHub APIs directly — use the MCP tools.
<!-- AUDIAGENTIC:END source-control/doctrine -->

<!-- AUDIAGENTIC:BEGIN coding-lsp/usage -->
## Code intelligence via LSP

The coding-lsp component provides language server protocol tools for code intelligence.
Use LSP tools instead of text search when doing symbol lookup, go-to-definition,
hover documentation, or finding all references — they are more precise.

Available tools (ag-lsp server):
- `lsp_symbols` — search workspace symbols by name
- `lsp_definition` — go to definition at file:line:column
- `lsp_hover` — type and documentation at a position
- `lsp_references` — all references to a symbol
- `lsp_doc_symbols` — file symbol outline
- `lsp_diagnostics` — type errors and warnings
- `lsp_rename_preview` — preview rename refactor

Position format for all tools: "line:column" (1-based).
These tools only operate on languages configured in .coding-lsp/lsp.json.
Use `lsp_config_status` (ag-lsp-mgmt server) to check which languages are active.
<!-- AUDIAGENTIC:END coding-lsp/usage -->
