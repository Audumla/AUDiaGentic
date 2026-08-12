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

### Composition candidates

- A binding names a component's public surface or a foundation capability —
  never an internal collaborator. This bounds the composition graph to
  component/capability boundaries, order tens permanently, not to the number
  of classes in the codebase. A component's internal collaborators are
  constructed by that component and never appear in the graph.
- Distinguish a **binding** from a **composed singleton**. A binding is a
  genuine choice between two or more implementations that configuration
  selects. A composed singleton is one implementation with no choice to make,
  composed because its construction/shutdown ordering is worth owning.
  Conflating the two — giving a single-implementation service a binding entry
  selected by profile or environment instead of composing it directly — is
  another way a composition root becomes a container.
- Evaluate lifecycle by scope, not by whether a mutable setter/getter exists
  today. A dependency whose construction and teardown are scoped to one
  process's entire operational lifetime is a valid candidate even if it is
  currently exposed as a module-global installed by a constructor and cleared
  by a destructor — that is ordinary object lifecycle, not runtime
  mode-switching. A dependency that is genuinely swapped *during* normal
  operation (not at process start/end) is not a build-time candidate; its
  internal mutability, if any, belongs inside the composed object's own
  method, not the graph.
- More than one composition root is expected, not a violation: different
  process kinds compose different graphs. A later root is deliberate when a
  new process kind needs its own composed dependencies; it is not evidence
  that the first root was wrong.
- For request/task-shaped work with many independent live instances, compose
  the **factory**, not the instances. The factory is the one binding — it
  legitimately owns the lifetime of the stateful resources (queues,
  connections, runtimes) that instances route through. What it mints is a
  freely-constructed, uncomposed **handle**: a thin object wrapping an
  identity plus delegating methods that re-read the durable source of truth
  on every call, never independently-cached state. A handle is never tracked
  by the graph, never a scope, and callers may hold as many as they like.
  Composing the handle instead of the factory is another route to a
  container: a per-request or per-task binding is not a component boundary.
- A composed surface is a controlled, tight API layer, not a general-purpose
  access point. It exposes the narrow set of operations its stated workflow
  needs, in a consistent method shape (mirroring existing composed surfaces'
  design and naming), not an accreting catalogue of "also add this while
  we're in here." A surface is not composed at every consumer that touches
  it, either — most consumers should reach it through a scoped adapter
  (protocol, MCP, CLI) calling the one composed thing, not by receiving the
  composed dependency directly. If a proposed binding's method count or
  consumer list keeps growing, that is a signal it has stopped being one
  component boundary and started being a dumping ground; split it or push
  the extra surface back behind the adapter layer instead of widening it.

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

- Put a capability in foundation only when it is domain-neutral and capabable
- of being reused in other modules. Shared component-domain logic stays with its
  component.
- Types are unified only when they share ownership, lifecycle, validation, and
  semantics; field overlap alone is insufficient.
- Split objects by cohesive responsibility. Size thresholds are review signals,
  not automatic architectural boundaries.
- Each durable artifact has one owner and one lifecycle path. Its mutation
  behaviour must preserve user-owned content, be atomic where feasible, support
  status/dry-run behaviour where applicable, and be testable.

### Evidence-led scope

- Build only the capability, contract, schema fields, and policy required by a
  current, evidenced use case or an approved owning plan item. Do not add
  speculative fields, modes, abstractions, compatibility paths, or generic
  machinery for requirements that do not yet exist.
- Design seams so a later owning item can extend them deliberately, normally by
  an additive versioned contract change. A possible future extension is not by
  itself a reason to implement it now.
- A proposed shared abstraction needs the same owner, lifecycle, validation,
  and semantics across at least two independent consumers. Similar field names
  or anticipated reuse are insufficient.
- Plan items must state the present trigger and keep deferred variants outside
  their delivery scope. When an implementation reveals a new requirement,
  create or revise its owning future item rather than silently broadening the
  current one.

## 4. Public Contracts and Safety

- Backward compatibility is not maintained by default. A migration updates all
  callers and deletes the obsolete API, alias, shim, dual route, and
  compatibility test. An exception requires a documented external obligation
  approved before implementation.
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
  references in the same change. Validation scope matches the change; do not
  call a subset the full suite.
- Exceptions require an explicit, documented rationale and bounded scope.

## 8. Protocol Adapter Boundaries

- MCP, CLI, event, and service-transport modules are inbound protocol adapters.
  They may translate parameters and authenticated caller context, apply
  transport-only timeouts/progress/logging, call an owning public client or
  application API, and serialize results and errors.
- Protocol adapters do not own domain validation, persistence, state
  transitions, dispatch, retries, provider selection, discovery, process or
  worker lifecycle, or resource arbitration.
- Dependencies point from adapters to framework-neutral public APIs. Core and
  API modules must not import MCP/FastMCP or own MCP-specific constants.
- An adapter must not import its component's store, queue, dispatch, service,
  provider adapter, or other implementation-internal module.

## Related guidance

- [Architecture Implementation Guidelines](ARCHITECTURE_GUIDELINES.md)
- [Observability Standards](OBSERVABILITY_STANDARDS.md)
- [Creating Components](CREATING_A_COMPONENT.md)
- [Creating a Harness](CREATING_A_HARNESS.md)
