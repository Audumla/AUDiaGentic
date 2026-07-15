# AUDiaGentic Architecture Standards

These are durable architectural invariants. A violation is an architectural
defect, not a style issue. Concrete APIs, paths, schemas, detector behaviour,
and component-specific rules belong in
[Architecture Implementation Guidelines](ARCHITECTURE_GUIDELINES.md).

## 1. Dependency Boundaries

The composition root wires the application. Dependencies otherwise point toward
shared or platform capabilities, never toward a requesting product domain.

| Layer | May depend on | Must not depend on |
|---|---|---|
| Foundation | Foundation; read-only `runtime/system` facts | Components; runtime orchestration |
| Platform components | Foundation; `runtime/system` | Requester/product components |
| Product components | Foundation; `runtime/system`; approved platform public APIs | Other component internals |
| Runtime orchestration | Foundation; `runtime/system`; approved platform public APIs; composition-root registrations | Optional component internals after wiring |
| Composition root | Any layer, to wire the application | — |

- `runtime/system` contains read-only live facts only. It imports no foundation,
  component, or runtime-orchestration code.
- Tests may cross production boundaries when needed to validate behaviour,
  migration safety, or architecture rules.
- Foundation names, event names, and extension keys are domain-neutral. Move a
  component-specific concept to its owning component.
- A registry does not remove a dependency. Resolved registry bindings remain
  dependency edges for architecture review and tests.

### Approved cross-component APIs

Cross-component imports are forbidden unless they target an approved platform
public API. Approval is explicit: record the owning platform component, public
module, permitted callers, and boundary constraints here. It does not permit
imports of the platform component's internals.

| Owner | Public module | Permitted callers | Boundary |
|---|---|---|---|
| `providers` | `audiagentic.components.providers.providers_api` | Product components, runtime orchestration, composition root | Provider-owned operations and reads only; no recipes, registries, adapters, serializers, or requester-domain imports. |

Future platform APIs require the same narrow, documented approval. They are
shared lower-layer seams, not general component-to-component exceptions.

## 2. Extensions and Configuration

- Entity declarations belong in configuration, not central Python lists or
  entity-name conditionals.
- Supported extensions use an owned, typed seam. Configuration declares an
  entity; code provides its implementation and composition-root wiring.
- Adding an entity must not require edits to a central dispatcher or unrelated
  component. Explicit registration is allowed when it is the declared
  execution-authority seam.
- Component discovery uses descriptors or package discovery. A descriptor is
  the canonical source of its component identifier.
- Generated assets use owned renderers or virtual-asset contributions; runtime
  does not branch on component-specific output paths.

## 3. Ownership and Abstraction

- Put a capability in foundation only when it is domain-neutral and has more
  than one independent consumer. Shared component-domain logic stays with its
  component.
- Types are unified only when they share ownership, lifecycle, validation, and
  semantics; field overlap alone is insufficient.
- Split objects by cohesive responsibility. Size thresholds are review signals,
  not automatic architectural boundaries.
- Each durable artifact has one owner and one lifecycle path. Its mutation
  behaviour must preserve user-owned content, be atomic where feasible, support
  status/dry-run behaviour where applicable, and be testable.

## 4. Public Contracts and Safety

- Public domain failures use `AudiaGenticError` with a stable, owning-component
  error code. Internal control flow may use native exceptions where they do not
  cross a public boundary.
- Errors, logs, results, timelines, and durable records must not expose secrets,
  credentials, raw prompts, or unredacted process output.
- External-service behaviour is explicit: classify failures, retry only bounded
  idempotent transient operations, and report safe degraded state when a
  best-effort operation can continue.
- Library code uses module loggers. CLI entry points may write user-facing output.

## 5. Events and Async Work

- A bus topic has one owner and a stable declared contract. Dynamic production
  topic construction is prohibited.
- Event handlers isolate boundary failures: they do not break bus dispatch and
  record a redacted durable failure suitable for operator action or manual
  recovery.
- Bus events communicate between components. Per-resource timelines and
  operational records are observability artifacts, not bus-topic declarations.

## 6. Platform and Provider Boundaries

- Host/editor behaviour is implemented behind a configurable adapter; product
  code does not embed host-specific commands or paths.
- A platform component exposes only its approved narrow public API. Requesters
  do not import adapters, serializers, handlers, or other implementation internals.
- Platform components remain requester-blind: requests carry needed data and
  opaque correlation/ownership context, not requester callbacks or domain policy.

## 7. Enforcement

- Architecture rules must have proportionate automated checks and focused tests.
- Migrations remove obsolete paths and verify affected production and test
  references. Validation scope matches the change; do not call a subset the
  full suite.
- Exceptions require an explicit, documented rationale and bounded scope.

## Related guidance

- [Architecture Implementation Guidelines](ARCHITECTURE_GUIDELINES.md)
- [Observability Standards](OBSERVABILITY_STANDARDS.md)
- [Creating Components](CREATING_A_COMPONENT.md)
