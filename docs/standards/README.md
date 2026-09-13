# Standards

These documents are normative guidance for new implementation and migrations.
They complement the managed repository instructions and current source,
schemas, configuration, and tests; those executable/current artifacts win if
there is a discrepancy.

- [Architecture standards](ARCHITECTURE_STANDARDS.md) — dependency direction,
  ownership, contracts, events, and protocol-adapter boundaries.
- [Architecture implementation guidelines](ARCHITECTURE_GUIDELINES.md) —
  practical patterns for registries, errors, redaction, async work, artifacts,
  and migrations.
- [Creating a component](CREATING_A_COMPONENT.md) — component layout,
  descriptors, managed files, MCP servers, features, options, and hooks.
- [Creating a harness](CREATING_A_HARNESS.md) — runtime/provider split,
  installation, runners, MCP surfaces, and viability gates.
- [Using recipes](USING_RECIPES.md) — declarative lifecycle and managed-config
  operation rules.
- [Secrets management](SECRETS_MANAGEMENT.md) — references, redaction,
  storage, testing, and prohibited patterns.
- [Observability standards](OBSERVABILITY_STANDARDS.md) — durable timelines,
  degraded outcomes, events, logs, and operational sidecars.
- [Docker test isolation](DOCKER_TEST_ISOLATION.md) — image, home, context,
  dependency, and harness-recipe isolation rules.

