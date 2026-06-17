# components/optional/release/release_please/

`release-please` installer and workflow renderer.

## Intent

Keep GitHub release automation assets in sync with AUDiaGentic expectations.

## Capabilities

- Install baseline `release-please` files into project.
- Re-render workflow files when package templates change.
- Finalize release output docs after ledger archival.
- Expose release-please management tools through MCP.

This area is automation-specific. Business rules about what changed live in `components/optional/ledger/`.
