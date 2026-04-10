# PKT-PRV-077 — Provider execution policy config contract

**Phase:** Phase 4.12
**Status:** READY_TO_START
**Owner:** Infrastructure

## Objective

Define a shared configuration contract for provider execution policy so adapters stop embedding
policy-bearing literals such as output format, safety mode, auto-approval posture, target type,
and timeout defaults directly in code.

## Scope

- define canonical config location in `.audiagentic/providers.yaml`
- define `providers.<provider-id>.execution-policy` keys for provider runtime flags
- document precedence between request overrides, provider config, project defaults, and any
  last-resort adapter fallback
- distinguish policy-bearing flags from ordinary stable CLI wiring
- document safe defaults for providers that support permissive or high-autonomy modes

## Initial keys

The first contract should be able to express at least:

- `output-format`
- `permission-mode`
- `safety-mode`
- `auto-approve`
- `full-auto`
- `ephemeral`
- `target-type`
- `timeout-seconds`

## Not in scope

- provider prompt-surface generation
- shared streaming hardening config under `stream-controls`
- provider-specific parsing logic

## Files likely to change

- `.audiagentic/providers.yaml`
- `docs/specifications/architecture/03_Common_Contracts.md`
- `docs/implementation/48_Phase_4_12_Provider_Optimization_and_Shared_Workflow_Extensibility.md`
- provider docs where execution flags are currently described informally

## Acceptance criteria

- a documented provider execution-policy contract exists in tracked config docs
- policy-bearing adapter flags have canonical config keys rather than implicit literals
- precedence is explicit and deterministic
- the contract distinguishes security/safety posture from ordinary provider CLI wiring
