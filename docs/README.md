# AUDiaGentic documentation

This directory is the documentation source for the current repository. Start
with the area that matches the work you are doing:

For the audit boundary and known findings, see
[Documentation status](DOCUMENTATION_STATUS.md).

| Area | Use it for | Authority and freshness |
| --- | --- | --- |
| [standards](standards/) | Architecture, component/harness creation, secrets, observability, recipes, and Docker rules | Active normative guidance; update when the implementation contract changes |
| [design](design/) | Design authority for cross-component architecture and gateway contracts | Current target decisions; each document states whether it is frozen, draft, or historical |
| [reference](reference/) | Provider capability, protocol, schema, endpoint, and integration reference | Code-facing reference; registries and schemas define the package's internal precedence |
| [examples](examples/) | Valid and invalid configuration fixtures and example scaffolds | Executable examples; keep them consistent with schemas and loaders |
| [planning](planning/) | Active work, completed work, reviews, and planning-process records | Project history and work tracking; completed records are historical evidence, not current implementation guidance |
| [releases](releases/) | Release notes, changelog, ledger, audit, and publishing records | Release-managed/generated material; follow the ledger process before editing |
| [research](research/) | Capability reviews and research evidence | Evidence and history; do not treat unverified findings as runtime authority |

## Documentation rules

- Source code, schemas, configuration, tests, and managed `AGENTS.md`
  instructions are the authority when documentation disagrees with them.
- Keep one canonical explanation for each active workflow. Link to it from
  other documents instead of copying a second contract.
- Mark superseded designs and historical planning records clearly; do not
  rewrite history to make it look current.
- Use repository-relative links and verify that local link targets exist.
- Never place secrets, tokens, raw prompts, or machine-specific credentials in
  documentation or examples.

## Current high-value entry points

- [Architecture standards](standards/ARCHITECTURE_STANDARDS.md)
- [Standards index](standards/README.md)
- [Design index](design/README.md)
- [Reference index](reference/README.md)
- [Examples index](examples/README.md)
- [Research index](research/README.md)
- [Creating a component](standards/CREATING_A_COMPONENT.md)
- [Creating a harness](standards/CREATING_A_HARNESS.md)
- [Shared gateway architecture](design/gateway-shared-service.md)
- [Gateway execution context](design/gateway-execution-context.md)
- [Provider capability reference](reference/PROVIDER_CAPABILITY_REFERENCE/README.md)
- [Planning process](planning/CREATING_PLANS.md)
- [Planning index](planning/README.md)
- [Release process](releases/README.md)
- [Testing guide](../tests/TESTING.md) — maintained test tiers, markers,
  fixtures, and execution guidance.
