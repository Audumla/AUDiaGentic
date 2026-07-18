# Reference Architecture

## Purpose

AUDiaGentic needs a normalized resource that answers five separate questions:

1. What can a harness do?
2. Which provider and endpoint families can it project?
3. How can AUDiaGentic control and observe its sessions?
4. Which telemetry can be obtained, at what scope, and with what confidence?
5. Which operations may be exposed through the capability gateway?

## Entity model

```text
Harness
  ├─ configuration projection
  ├─ execution transport
  ├─ control/session transport
  ├─ tool transport
  └─ observability surfaces

Provider instance
  ├─ credential owner and account scope
  ├─ endpoint family
  ├─ protocol dialect
  ├─ vendor service
  └─ telemetry adapters

Model endpoint
  ├─ upstream model vendor
  ├─ model identifier
  ├─ context and modality capabilities
  ├─ pricing
  └─ qualification state

Harness binding
  ├─ harness instance
  ├─ provider instance
  ├─ model endpoint
  └─ session identity
```

## Capability layers

| Layer | Examples |
|---|---|
| Provisioning | installation, executable discovery, version detection |
| Configuration | root relocation, alternate file, inline overlay, managed policy |
| Connectivity | vendor APIs, compatible endpoints, local runtimes, gateways |
| Protocol | OpenAI Responses, Chat Completions, Anthropic Messages, Gemini, ACP, MCP |
| Execution | direct CLI, SDK, ACP, native RPC, remote control |
| Session | create, resume, live attach, external injection, cancellation |
| Tools | native tools, MCP tools, client services, permissions |
| Telemetry | balance, usage, quota, context, cost, local runtime |
| Governance | provenance, confidence, evidence, probe state, lifecycle |

## Fact lifecycle

```text
observed → documented → normalized → probed → verified → stale/deprecated
```

A claim may remain useful while `observed` or `documented`, but scheduler-critical decisions should prefer `verified` facts and degrade gracefully when only weaker evidence exists.

## Required fact metadata

```yaml
state: verified | documented | observed | expected | unsupported | unknown | stale
source_kind: official-doc | source-code | runtime-probe | harness-event | estimate | scrape
last_validated: YYYY-MM-DD
version_scope: string | null
evidence_ids: [string]
limitations: [string]
```

## Derived views

Human-readable matrices are derived views. They must not become a second source of truth.

Runtime code consumes **provider descriptors** (`config/providers/*.yaml` — MA20 declarations plus MA19 `capability_facts`), never this package (RV560; MA19 forbids runtime imports of reference views). The registries and schemas here structure the evidence that gets projected into those descriptors; people use the domain documents and generated matrices.
