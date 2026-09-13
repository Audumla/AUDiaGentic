# Reference documentation

Reference material is code-facing and evidence-based. It describes contracts,
schemas, registries, integration surfaces, and audits; it does not replace
runtime configuration or source code.

- [Provider capability reference](PROVIDER_CAPABILITY_REFERENCE/README.md) —
  provider, harness, protocol, endpoint, configuration, execution, and
  telemetry evidence with package-local authority rules.
- [Agent harness gateway integration](AGENT_HARNESS_GATEWAY_INTEGRATION.md) —
  integration reference for harness and gateway boundaries.
- [Managed mutation audit](MANAGED_MUTATION_AUDIT.md) — audit record for
  managed file mutation ownership and atomic-write boundaries.

The provider capability package includes a generated integrity manifest under
`PROVIDER_CAPABILITY_REFERENCE/validation/manifest.json`. When package files
change, regenerate or synchronize that manifest; a matching hash and byte
count proves package completeness, not capability freshness.

Validation dates belong to individual facts and reports. Do not infer current
support from a file's presence; distinguish verified, expected, unknown, and
unsupported states as defined by the referenced contract.
