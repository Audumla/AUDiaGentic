# channels/

## Purpose
Operator-facing surfaces through which humans and tools interact with AUDiaGentic. Each channel subdomain owns the entry point for a specific operator surface.

## Ownership
- CLI argument parsing and dispatch (`cli/`)
- VS Code channel integration (`vscode/` — scaffold)
- Surface-specific input normalization before handoff to execution

## Must NOT Own
- Job orchestration logic (→ `execution`)
- Provider dispatch (→ `interoperability`)
- Durable state persistence (→ `runtime/state`)
- Release audit (→ `release`)

## Allowed Dependencies
- `foundation/contracts` — error types and validation
- `foundation/config` — project and provider config
- `runtime/state` — read job records for command dispatch
- `execution/jobs` — launch jobs and control them
- `release` — trigger release bootstrap

## Subdomains

### cli/
Command-line interface. Entry point: `main.py`.
Commands: `prompt-launch`, `job-control`, `session-input`, `release-bootstrap`,
`providers-status`, `lifecycle-stub`, `refresh-model-catalog`, `prompt-trigger-bridge`.

### vscode/ (scaffold — deferred)
Scaffold reserved for a future VS Code editor integration channel.
No executable code yet. See knowledge for domain design intent.

## Design Rule
Channels are thin — they parse operator input, validate surface-level constraints, and delegate to `execution` or `release`. Channel code must not contain business logic that belongs to the domain it is calling.
