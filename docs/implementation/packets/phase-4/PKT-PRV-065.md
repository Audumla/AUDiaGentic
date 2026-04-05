# PKT-PRV-065 — opencode prompt-surface integration

**Phase:** Phase 4.4
**Status:** IN_PROGRESS
**Owner:** opencode

## Objective

Align opencode with the shared prompt-surface contract so canonical `ag-*` tags, aliases, and
provider defaults resolve through the same repo-owned syntax model used by the other primary
providers.

## What is implemented

- opencode provider docs use the canonical `ag-*` vocabulary
- provider alias `opc` is documented and aligned with `.audiagentic/prompt-syntax.yaml`
- combined alias examples such as `@agr-opc` are documented through the config-managed syntax
  model rather than a provider-specific grammar
- opencode is now represented in the provider docs as a wrapper-normalize surface instead of a
  one-off launch path
- provider-config parity is still incomplete because `.audiagentic/providers.yaml` does not yet
  contain the `opencode` entry required by provider selection and health checks

## Acceptance Criteria

- prompt-surface docs use canonical tag names and config-managed aliases
- required local assets and wrapper expectations are documented
- opencode prompt-surface behavior matches the shared bridge contract
- `.audiagentic/providers.yaml` contains the matching `opencode` provider entry
