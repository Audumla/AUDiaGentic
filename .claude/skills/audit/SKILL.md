# audit skill

Use this skill for canonical `@audit` launches.

Trigger:
- first non-empty line resolves to `audit`

Do:
- perform deterministic audit of build state, dependencies, and contracts
- produce audit summary with findings
- identify risk or drift from locked contracts

Do not:
- make changes based on audit findings without explicit approval
- redefine the canonical grammar
