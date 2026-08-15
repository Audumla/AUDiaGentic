# AUDiaGentic Agent-Surface & Capability Convergence — Execution Run Sheet

**Repository:** `Audumla/AUDiaGentic`
**Branch:** `agent-surface-refactor`
**Reviewed remote HEAD:** `bbf48fa00eb68e8b6021b5ae62f4b7602c9bb420`
**Purpose:** complete the existing agent-platform cutover, converge capability/session modelling, then wire admission and protocol projections without introducing another compatibility architecture.

---

## 1. Implementation doctrine

The target pipeline is:

```text
AgentsConfigDocument
        │
        ▼
ResolvedAgentComposition
        │
        │ ExecutionProfile
        ▼
Resolved exact provider surface
        │
        │ canonical capability support
        │ typed facts
        │ evidence
        ▼
AgentAdmission
        │
        │ RoleManifest
        │ eligible instance IDs
        ▼
Gateway execution request
        │
        ▼
AS101 exact instance/model/source binding
        │
        ▼
provider materialization/session
        │
        ├───────────┬───────────┐
        ▼           ▼           ▼
       ACP         A2A         ASA
```

This is deliberately **not** another new object hierarchy.

The branch already has:

* `ResolvedAgentComposition`;
* `AgentAdmission`;
* canonical configuration;
* Context and Work;
* Gateway execution;
* provider session surfaces;
* session binding;
* capability catalogue;
* Standard Agents projection.

The implementation should evolve those rather than create:

```text
ConfiguredAgentTarget
SelectedAgentTarget
ResolvedHarnessTarget
AdmittedHarnessTarget
BoundHarnessTarget
MaterializedHarnessTarget
```

as six new data representations.

Use stage names where useful for workflow/state:

```text
CONFIGURED
RESOLVED
ADMITTED
BOUND
MATERIALIZED
```

but create a new data type only when a stronger invariant genuinely requires one.

---

# 2. Verified current-state findings

## 2.1 The previous destructive migration is not finished

`components/agent_jobs` still exists as a substantial namespace while the new Agents component already contains canonical Context, Work, configuration, Gateway, ACP, A2A and Standard Agents functionality.

These compatibility APIs also remain:

```text
components/agents/models/role_api.py
components/agents/models/agent_definition_api.py
components/agents/models/execution_profile_api.py
```

Therefore:

> **Do not build the new capability architecture on top of the remaining compatibility architecture.**

The destructive cutover is an implementation prerequisite.

---

## 2.2 Canonical configuration is already substantially correct

`AgentsConfigDocument` is frozen and recursively deep-frozen.

Its mapping keys are canonical identity and conflicting embedded IDs are rejected.

Do **not** replace this repository/configuration design.

The remaining mutability problem is primarily in projected authored models.

`ExecutionProfile` is mutable and carries a mutable `params` dictionary. Its store also mutates default state.

`AgentDefinition` is mutable, retains the old `role_id` compatibility form and has mutable `advertised_skills`.

`Role` is already frozen.

---

## 2.3 Capability modelling is currently duplicated

Agents defines:

```python
CapabilityRequirementId
LaunchContribution
ResolvedCapability
RoleManifest
```

and `CapabilityVocabulary` defines capability semantics principally through launch contributions.

The resolver:

* accepts `Any` evidence;
* accepts several unrelated evidence shapes;
* converts raw strings into requirement IDs;
* performs string-oriented support matching;
* throws ordinary `ValueError` failures.

This must be replaced rather than extended.

---

## 2.4 Providers already have a newer capability model

`ProviderDescriptor.capabilities` contains the newer unified provider capability representation.

However the same descriptor still independently carries:

```text
capabilities
session_surfaces
harness_observability
```

and its historical:

```python
capability_facts
```

accessor currently returns:

```python
()
```

The old `ProviderCapabilityFact` model also remains and contains dynamically generated validation error identities.

This is unfinished convergence.

---

## 2.5 Runtime surface facts are duplicated

`ResolvedSessionSurface` contains:

* identity operations;
* controls;
* ownership;
* mapping requirements;
* concurrency;
* lifecycle;
* evidence;
* content support.

The session-binding contracts separately carry `SessionMappingCapabilities` with overlapping concepts including resume/attach/discovery/project/context/concurrency.

Do **not** simply delete one model.

First classify every property as:

```text
capability support
fact
operation
identity
binding relation
evidence
```

and remove only the conceptual duplicates.

---

## 2.6 Surface-resolution errors are currently too lossy

`resolve_session_surface()` intentionally returns a stable unsupported snapshot instead of raising.

That currently means several materially different failures can collapse into effectively the same result:

```text
provider missing
provider disabled
version unresolved
surface unsupported
platform incompatible
evidence missing
adapter unavailable
probe exception
adapter resolution exception
```

The version probe and adapter checks contain broad exception handling that converts failures into absence.

This is incompatible with capability admission because:

```text
"Codex does not implement this"
```

cannot mean the same thing as:

```text
"our Codex adapter import is broken"
```

---

## 2.7 Provider loading also conflates strict and tolerant behaviour

The provider descriptor loader still contains a central mechanism-schema branch and separately parses session surfaces and harness observability.

Directory loading catches descriptor failures, logs them and returns a partial provider collection with errors retained separately.

That may be useful for diagnostics.

It is dangerous for authoritative execution.

Do not simply change it globally to fail-fast.

Create explicit semantics:

```text
strict authoritative load
tolerant diagnostic load
```

and ensure execution uses the strict path.

---

## 2.8 Gateway admission is genuinely missing

`InProcessGatewayApplication.submit_agent_work()` currently gets the Context execution profile and proceeds towards `submit_execution_request()` without first freezing:

```text
exact provider surface
provider capability evidence
RoleManifest
eligible instance IDs
AgentAdmission
```

This is the concrete AS85 integration point.

---

## 2.9 Standard Agents currently resolves too much itself

Its projector takes raw dictionaries and requires exactly one execution-profile instance, meaning the projector itself partially decides whether an Agent is portable/projectable.

That responsibility must move upstream.

The projector should receive a typed already-resolved target.

---

# 3. Hard modelling rules

Apply these during every slice.

| Concept       | Definition                                     |
| ------------- | ---------------------------------------------- |
| Capability    | Something the executing surface can do         |
| Fact          | Property constraining/describing behaviour     |
| Mechanism     | How the capability is implemented              |
| Evidence      | Why the claim is trusted                       |
| Policy        | Whether AUDiaGentic allows use                 |
| Configuration | Instructions/configuration needed by mechanism |
| State         | Current processing/lifecycle stage             |
| Projection    | Representation in ACP/A2A/ASA/etc              |

Examples:

```text
turn.steer                    CAPABILITY
session.resume                CAPABILITY

concurrent_attachments=false  FACT
same_project_required=true    FACT

ACP                           MECHANISM/PROTOCOL
stdio                         TRANSPORT/MECHANISM
native API                    MECHANISM

validated against 1.4.2       EVIDENCE

adapter_ref                   PRIVATE IMPLEMENTATION
```

Never turn these categories into aliases for one another.

---

# 4. Phase 0 — Freeze and inventory the starting state

### Goal

Establish a reproducible starting point and mechanically locate every compatibility/capability/session seam before editing.

### Run

```bash
set -euo pipefail

git switch agent-surface-refactor

test -z "$(git status --porcelain)" || {
    echo >&2 "Working tree is not clean"
    exit 1
}

BASE_SHA="$(git rev-parse HEAD)"
printf 'Initial BASE_SHA=%s\n' "$BASE_SHA"
```

For this reviewed version the expected initial remote revision is:

```text
bbf48fa00eb68e8b6021b5ae62f4b7602c9bb420
```

If the local branch has moved materially beyond it, **do not reset it**.

Instead rerun the inventories below and compare affected code before executing the corresponding slice.

### Capture the architecture inventory

```bash
git ls-files src tests > /tmp/audiagentic-files.before

git grep -nE \
  'components\.agent_jobs|AgentTask|AgentTaskFactory' \
  -- src tests || true

git grep -nE \
  'role_api|agent_definition_api|execution_profile_api' \
  -- src tests || true

git grep -nE \
  'CapabilityRequirementId|ProviderCapabilityFact|ResolvedCapability|CapabilityVocabulary' \
  -- src tests || true

git grep -nE \
  'SessionMappingCapabilities|SessionMappingCapability|SessionOwnership\b' \
  -- src tests || true

git grep -nE \
  'session_surfaces|harness_observability|capability_facts' \
  -- src tests || true

git grep -nE \
  'except +Exception|except +BaseException' \
  -- src/audiagentic/components/providers \
     src/audiagentic/components/agents || true

git grep -nE \
  'provider_id *==|if .*provider_id' \
  -- src/audiagentic/components/agents || true

git ls-files |
  grep -E \
  '(_capabilities|_families|provider_specs|providers?.*\.ya?ml)' \
  || true
```

### Planning reconciliation

Locally enumerate:

```bash
find .planning -type f \
  \( -iname 'AS*.md' -o -iname 'AG*.md' -o -iname 'SH*.md' \) \
  -print | sort
```

Then reconcile the implementation sequence against at least:

```text
AS72
AS84
AS85
AS86+
AS94
AS96
AS97
AS98
AS101
AS102
AS104
```

Do not let an old item whose ownership has moved dictate the implementation.

### Exit condition

A call-site list exists for every destructive target.

No code yet.

---

# 5. Phase 1 — Complete AS72/error convergence first

## Objective

Make resolution/admission failures trustworthy before capability resolution starts depending on them.

---

## 5.1 Remove generated capability-fact error identities

Target:

```text
components/providers/descriptors/capability_facts.py
```

Current historical model dynamically constructs validation identities.

### Change

Register explicit static errors for every surviving public failure.

Then migrate/delete `ProviderCapabilityFact` later in the capability cutover.

Do not preserve dynamic codes just because this type is scheduled for deletion; capability migration will otherwise introduce dependencies on an invalid error path.

---

## 5.2 Establish resolution failure semantics

Do **not** make one enormous new status enum.

Use two categories.

### Expected resolution outcomes

```text
SUPPORTED
UNSUPPORTED
UNPROVEN
UNAVAILABLE
```

These are normal domain outcomes.

### Exceptional failures

Use registered AUDiaGentic errors for:

```text
INVALID
FAILED
```

Examples:

```text
malformed packaged surface declaration
invalid adapter reference
unexpected version-probe failure
provider descriptor contract violation
corrupt evidence record
```

These should not be returned as `UNSUPPORTED`.

---

## 5.3 Refactor `session_surface_resolution.py`

Current target:

Replace semantics such as:

```python
try:
    version = probe()
except Exception:
    version = None
```

with:

```text
known "not installed"
    -> UNAVAILABLE

known unsupported surface/version
    -> UNSUPPORTED

required evidence absent
    -> UNPROVEN

probe unexpectedly fails
    -> registered resolution error, cause preserved
```

Likewise adapter resolution:

```text
surface legitimately has no adapter
    -> expected according to schema

declared adapter cannot import/resolve
    -> configuration/implementation error
```

Never:

```text
broken adapter == unsupported harness
```

---

## 5.4 Split provider loading semantics

Target loader:

Inventory every caller first:

```bash
git grep -n 'load_providers_from_directory' -- src tests
```

Then establish explicit APIs or modes resembling:

```python
load_providers_strict(...)
load_providers_diagnostic(...)
```

or a comparably clear typed interface.

### Strict

Used for:

```text
runtime execution
admission
authoritative startup
```

Invalid configured provider → fail.

### Diagnostic

Used where partial discovery is intentionally useful:

```text
CLI inspection
doctor/status
catalogue diagnostics
```

Result must expose the failures explicitly.

Never let execution accidentally receive the diagnostic partial set.

---

## 5.5 Error payload requirements

Every capability/admission error should include enough context to act on it:

```text
stage
agent_id
role_ids
execution_profile_id
provider_id
surface_id
capability_id where relevant
evidence ID where relevant
cause
remediation
```

Example conceptual result:

```text
stage: capability-admission
agent_id: reviewer
profile_id: codex-main
provider_id: codex
surface_id: codex-app-server

capability:
    turn.steer

outcome:
    UNPROVEN

reason:
    exact installed surface has no qualifying validation evidence

remediation:
    validate the surface or select a different execution profile
```

Do not expose internal stack/config details in a public protocol representation, but preserve them in the internal causal error chain.

---

## Validation

Run the existing relevant error/provider tests and then:

```bash
ruff check src tests
pyright
git diff --check
```

Add tests proving:

1. unsupported capability stays unsupported;
2. missing evidence is unproven;
3. disabled/not-installed provider is unavailable;
4. malformed surface declaration raises;
5. adapter import failure raises;
6. original exception survives as cause;
7. strict descriptor load fails;
8. diagnostic load reports the same defect without hiding it.

### STOP

If a test requires translating an unexpected internal exception to `UNSUPPORTED`, stop and fix the error model.

### Checkpoint

Commit only when AS72 error identity and cause semantics are stable.

---

# 6. Phase 2 — Complete the old destructive agent-platform cutover

This is the most important prerequisite.

---

## 6.1 Remove legacy model APIs

Targets:

```text
agents/models/role_api.py
agents/models/agent_definition_api.py
agents/models/execution_profile_api.py
```

First:

```bash
git grep -nE \
  'role_api|agent_definition_api|execution_profile_api' \
  -- src tests
```

For each caller:

```text
read operation
    -> AgentsConfigRepository / AgentsConfigService

mutation
    -> canonical repository CAS/update path

test helper
    -> canonical repository fixture
```

Do **not** recreate equivalent methods elsewhere for convenience.

Once zero production callers remain, delete the old APIs and migrate/remove their tests in the same slice.

---

## 6.2 Freeze `AgentDefinition`

Current implementation is mutable and carries the singular `role_id` compatibility path.

Target invariant:

```python
@dataclass(frozen=True, slots=True)
class AgentDefinition:
    agent_id: ...
    name: ...
    prompt_id: ...
    role_ids: tuple[...]
    execution_profile_id: ...
    advertised_skills: tuple[...]
    ...
```

The exact fields should follow the current canonical configuration.

### Remove

Once call sites are clean:

```text
constructor role_id compatibility
role_id compatibility property
mutable advertised_skills
old parsing variants only retained for already-migrated legacy config
```

If legacy on-disk migration is still a supported entrypoint, isolate that transformation in the migration layer.

Do not leave compatibility in the canonical model.

---

## 6.3 Freeze `ExecutionProfile`

Current implementation is mutable.

Change:

```text
params dict
    -> recursively frozen mapping

instances
    -> tuple

object
    -> frozen dataclass
```

Default selection must no longer mutate stored profile objects.

Instead calculate default identity when constructing the canonical collection or replacing repository state.

---

## 6.4 Preserve canonical document authority

Do **not** reimplement its freezing/identity machinery.

The canonical document already handles mapping-key identity and recursive freezing.

All authored configuration mutation should end at:

```text
repository replacement/CAS
```

not:

```text
model.foo = ...
store object mutation
```

---

## 6.5 Remove `agent_jobs`

Inventory it:

```bash
find src/audiagentic/components/agent_jobs -type f -print | sort

git grep -n \
  'components.agent_jobs' \
  -- src tests
```

For each module use exactly one classification:

| Existing semantic         | Destination              |
| ------------------------- | ------------------------ |
| Already replaced          | delete                   |
| Work lifecycle            | `components/agents/work` |
| Generic lifecycle utility | Foundation               |
| Provider execution        | Providers                |
| Agent configuration       | Agents configuration     |
| External protocol ingress | protocol adapter         |
| Compatibility only        | delete                   |

Never create:

```text
agent_jobs_compat
legacy_agent_jobs
agent_tasks_v2
```

---

## 6.6 Remove old trigger authority

Locate:

```bash
git grep -nE \
  'event-triggers|event_triggers|agent-jobs' \
  -- src tests . || true
```

The canonical configuration/Work path should be sole authority.

If old trigger code contains validation behaviour that canonical Work lacks:

1. migrate the validation;
2. add focused canonical test;
3. delete old authority immediately.

Do not make canonical trigger code read two config locations.

---

## 6.7 Delegation should already use Work

`GatewayApplication` already exposes parent→child Work support.

Therefore old delegation code based on:

```text
AgentTask
AgentJob
```

must be rewritten toward:

```text
parent Work
    ↓
child Work
```

not carried forward.

---

## Destructive gate

These should be zero:

```bash
git grep -nE \
  'components\.agent_jobs|AgentTask|AgentTaskFactory' \
  -- src tests && exit 1 || true

git grep -nE \
  'role_api|agent_definition_api|execution_profile_api' \
  -- src tests && exit 1 || true
```

Run the focused Agents tests, then:

```bash
ruff check src tests
pyright
python tests/run_all.py --fast
```

The repository's existing runner should remain the canonical broad validation mechanism.

### STOP

If deleting one old API reveals execution semantics with no canonical owner, stop that deletion and determine the correct owner.

Do **not** install another adapter around it.

---

# 7. Phase 3 — Concept-equivalence cut

Do this before creating canonical capability IDs.

The point is to find duplicates before creating another generation of them.

---

## 7.1 Session concept table

For every existing property/types in:

```text
foundation/transports/session_surface.py
foundation/transports/session_binding.py
providers/contracts/session_binding.py
```

classify it.

Expected broad outcome:

### Keep as binding identity/operation concepts

Likely:

```text
ProviderSessionRef
BindingRelation
binding intent
binding update/result
provider attach/open/resume operation protocols
```

These represent actual binding operations or durable identity.

### Become canonical capability support

Examples:

```text
resume supported
attach supported
discover supported
turn steering supported
turn cancel supported
```

There should be one support representation.

### Become facts

Examples:

```text
ownership
reference namespace
requires same project
requires same context
concurrent attachments
attach while active
```

These are not capabilities.

---

## 7.2 Special rule for operation enums

An enum can remain if it defines an invocation contract.

For example:

```text
TurnSteerRequest
SessionResumeRequest
```

is different from:

```text
surface supports turn.steer
surface supports session.resume
```

Do not delete a useful operation type merely because capability identity now exists.

But do not retain two separate ways of expressing whether the operation exists.

---

## 7.3 Resolve Foundation naming collision

`foundation/capabilities` currently represents a cross-boundary service-registration facility, not this semantic capability taxonomy.

Before adding semantic capability contracts either:

### Option A — preferred

Rename/move that service-registration seam according to what it actually does.

Then the semantic namespace may use the clear name.

### Option B

Place the shared semantic types under an existing neutral Foundation contract namespace.

Do not let:

```text
foundation.capabilities
```

mean both:

```text
harness status service registry
```

and:

```text
semantic execution abilities
```

---

## Exit artefact

Before implementation proceeds, the implementation review should be able to produce:

```text
old symbol
→ semantic concept
→ canonical owner
→ keep/change/delete
```

for every duplicate.

### STOP

If two types can be converted losslessly in both directions and carry the same invariant, they are probably the same concept.

Do not create a mapper. Merge them.

---

# 8. Phase 4 — Introduce the minimum canonical capability identity

This is where I would simplify the earlier proposal.

Do **not** immediately add four new classes named:

```text
CapabilityDefinition
CapabilityDeclaration
CapabilitySupport
CapabilityRequirement
```

because parts of those concepts already exist.

---

## 8.1 Add only the missing shared identity first

Introduce one neutral:

```python
@dataclass(frozen=True, slots=True, order=True)
class CapabilityId:
    value: str
```

with canonical validation.

Use the same type in:

```text
Role
provider catalogue
resolved surface support
RoleManifest
external safe projections where appropriate
```

No:

```text
CapabilityRequirementId
AgentCapabilityId
ProviderCapabilityId
SurfaceCapabilityId
```

---

## 8.2 Evolve `CapabilityKind` instead of replacing it unnecessarily

The provider catalogue already has meaningful concepts:

```text
id
domain
authority
family_id
cardinality
mechanism_schema
canonical_kind
```

Refactor this existing definition toward the canonical catalogue.

Add only concepts actually required, probably:

```text
scope
role_requireable
```

Do not rename it merely to obtain a cleaner architecture diagram unless the existing name materially misrepresents the final concept.

---

## 8.3 Reuse provider `Capability` as the declaration where possible

Providers already have a unified authored `Capability`.

Prefer:

```text
existing Provider Capability
    +
CapabilityId
```

over creating:

```text
CapabilityDeclaration
```

that simply mirrors it.

---

## 8.4 Introduce a resolved support type only if needed

A genuine distinct concept exists for:

```text
"the exact installed surface has proven support for capability X"
```

That may justify something small such as:

```python
@dataclass(frozen=True, slots=True)
class CapabilitySupport:
    capability_id: CapabilityId
    evidence_ids: tuple[str, ...]
```

Potentially include support state if the exact resolver requires it.

Do not turn this into another provider-specific class hierarchy.

---

# 9. Phase 4A — Taxonomy spike before mass migration

Test the taxonomy against heterogeneous surfaces.

Use representative examples from:

```text
Codex App Server
OpenCode server
Claude Code
Pi
```

Do not migrate every provider yet.

The purpose is to make bad abstractions fail cheaply.

---

## Proposed semantic domains

Treat these as an initial test, not immutable doctrine:

```text
session
turn
interaction
observation
workspace
delegation
content
configuration
model
```

Examples:

```text
session.open
session.attach
session.resume
session.discover
session.fork
session.close

turn.cancel
turn.interrupt
turn.steer

observe.lifecycle
observe.output
observe.tool
observe.progress

workspace.read
workspace.write
workspace.search
workspace.shell
workspace.diff
workspace.checkpoint
workspace.worktree

delegate.child
delegate.background
delegate.message
delegate.tasks
```

Before finalising interaction IDs, compare with the existing Foundation Interaction vocabulary and reuse it rather than creating synonyms.

---

## Things that should generally not become capability IDs

```text
ACP
A2A
stdio
WebSocket
native-api
provider-session-ref
owned
adopted
same-project
concurrent-attachments
linux-amd64
version >= ...
adapter path
hook name
```

---

## Scope

A useful distinction remains:

```text
provider scoped
surface scoped
```

### Provider

What AUDiaGentic can configure/manage for that integration:

```text
MCP configuration
hooks
models
plugins
managed files
installation
```

### Surface

What an exact execution surface can perform:

```text
resume
steer
shell
delegate
observe output
```

Roles should normally require the latter.

---

## STOP

If a canonical capability ID needs:

```text
codex.*
claude.*
opencode.*
pi.*
```

the abstraction probably belongs to the provider mechanism rather than the canonical capability vocabulary.

---

# 10. Phase 5 — Converge provider surface configuration

The current descriptor splits execution knowledge into:

```text
capabilities
session_surfaces
harness_observability
```

Converge the overlapping runtime pieces.

---

## 10.1 Target conceptual structure

Illustrative:

```yaml
provider_id: codex

capabilities:
  # provider/integration management capabilities
  ...

surfaces:
  codex-app-server:
    version: ...

    capabilities:
      session.resume:
        evidence: [app-server-linux]

      turn.steer:
        evidence: [app-server-linux]

      observe.output:
        evidence: [app-server-linux]

    session:
      ownership: owned
      ref_namespace: ...
      requires_same_project: true
      requires_same_context: true
      concurrent_attachments: false

    observation:
      correlated: true
      ordered: true
      idempotent: false

    evidence:
      app-server-linux:
        platform: ...
        validated: true
        reference: ...

    implementation:
      adapter: ...
      protocol: ...
```

Exact field names should follow existing project conventions.

---

## 10.2 Important configuration rules

### Mapping key is identity

Do not write:

```yaml
codex-app-server:
  surface_id: codex-app-server
```

unless a serialization contract genuinely requires it.

### Evidence is referenced

If ten capabilities are proven by one record:

```text
define evidence once
reference ten times
```

Do not duplicate the complete evidence payload.

### Facts are typed and grouped

Good:

```yaml
session:
  concurrent_attachments: false
```

Bad:

```yaml
facts:
  concurrent_attachments: false
  random_other_property: ...
```

No generic junk drawer.

### Implementation is private

The resolved public model must not expose:

```text
adapter_ref
module path
native command
raw CLI switch
endpoint implementation
native event name
native payload
```

---

## Migration order

1. migrate one rich surface;
2. make all tests pass;
3. migrate one materially different surface;
4. review taxonomy/config;
5. only then convert the rest.

After all consumers move, delete the old blocks.

### Hard invariant

```text
same fact authored twice = schema defect
```

---

# 11. Phase 6 — Remove central branching

---

## 11.1 Replace `_project_mechanism()` branching

Current loader has a central mechanism-schema conditional.

Create a decoder registry roughly:

```text
schema ID
    ↓
decoder implementation
```

Example shape:

```python
class MechanismDecoder(Protocol):
    def decode(self, raw: Mapping[str, object], context: DecodeContext) -> object:
        ...
```

Registry:

```python
registry.require(schema_id).decode(raw, context)
```

Do not scatter:

```python
if schema == ...
elif schema == ...
```

through callers.

---

## 11.2 Family polymorphism

The current `FamilyDeclaration` reflects automation-oriented payload/result/mode semantics.

If runtime families genuinely need different invariants, decode once into polymorphic family contracts.

For example:

```text
CapabilityFamily
    ├── AutomationFamily
    └── RuntimeFamily
```

Do not build one class with twenty optional fields.

Do not repeatedly switch on family type after loading.

---

# 12. Phase 6B — Decompose exact surface resolution

Do not make each check a durable state.

This is processing composition.

Conceptually:

```text
SurfaceResolutionContext
      │
      ▼
ProviderResolution
      │
      ▼
VersionResolution
      │
      ▼
SurfaceSelection
      │
      ▼
PlatformResolution
      │
      ▼
EvidenceResolution
      │
      ▼
ImplementationResolution
      │
      ▼
Resolved surface
```

Each processor:

```text
immutable input
→ enriched immutable output

or

registered domain error
```

Provider-specific behaviour stays behind provider strategies/adapters.

### Rule

There should be no new central:

```python
if provider_id == "codex":
...
elif provider_id == "claude":
...
```

in Agents or generic surface resolution.

---

# 13. Phase 6C — Build progressive Agent resolution without object proliferation

The current code already gives us much of the stage model.

## CONFIGURED

Reuse:

```text
ResolvedAgentComposition
```

It already represents the selected canonical Agent/Prompt/Role/ExecutionProfile composition.

Tighten the remaining `Any` fields as the canonical model stabilises.

---

## RESOLVED

If no current type adequately represents this invariant, introduce **one** object containing:

```text
composition identity
execution profile identity
exact provider
exact surface
surface version/platform where relevant
canonical CapabilitySupport set
typed facts
evidence fingerprint
```

A short name such as:

```text
ResolvedAgentTarget
```

is adequate.

Do not call it `ResolvedHarnessExecutionSurfaceTargetComposition`.

---

## ADMITTED

Evolve the existing:

```text
AgentAdmission
```

rather than adding an `AdmittedAgentTarget`.

It should hold:

```text
resolved target identity/fingerprint
RoleManifest
eligible_instance_ids
```

---

## BOUND

Do not invent another semantic selection layer.

AS101 already owns exact runtime source/model/instance choice.

Its result is the binding.

---

## MATERIALIZED

Reuse existing provider launch/session/materialisation contracts wherever those already represent the invariant.

---

# 14. Phase 7 — Rewrite AS84 around canonical capability support

---

## 14.1 Role

Change:

```python
required_capabilities: tuple[CapabilityRequirementId, ...]
```

to:

```python
required_capabilities: tuple[CapabilityId, ...]
```

Then delete:

```text
CapabilityRequirementId
```

after zero call sites remain.

---

## 14.2 Remove `CapabilityVocabulary`

Its current role as an Agents-owned second vocabulary should disappear.

Capability meaning comes from the canonical catalogue.

Provider surface support comes from exact provider resolution.

Agents does not maintain another translation namespace.

---

## 14.3 Remove `ResolvedCapability` if canonical support replaces it exactly

Current:

```text
ResolvedCapability
    requirement_id
    evidence_ids
    launch
```

mixes:

```text
support
evidence
launch/materialization
```

Separate those concepts.

`RoleManifest` should contain the canonical resolved support subset.

Launch/materialisation effects should be produced by the relevant admitted/materialisation mechanics.

---

## 14.4 `LaunchContribution`

Do not automatically delete it.

Ask:

> Does this represent a real independent materialisation result?

If yes, retain/move it under the materialization concern.

If it exists only because old CapabilityVocabulary equated a capability with environment/MCP/arguments, delete it.

---

## 14.5 Role resolution

Target:

```text
Role.required_capabilities
          │
          ▼
exact ResolvedAgentTarget capabilities
          │
          ▼
all required IDs satisfied?
          │
     ┌────┴────┐
     │         │
    yes        no
     │         │
     ▼         ▼
RoleManifest   actionable admission error
```

The resolver should accept one typed evidence/support contract.

Delete:

```text
Any
dict-or-object-or-iterable guessing
string-shape heuristics
```

from the admission path.

---

## 14.6 Fingerprint

Fingerprint only semantic execution invariants.

Include where applicable:

```text
Role IDs
canonical capability IDs
support/evidence identity
semantic materialisation requirements
```

Exclude:

```text
timestamps
diagnostic prose
dictionary ordering
stack traces
logging metadata
```

Test same result across repeated runs/processes/order permutations.

### Gate

Do not start AS85 wiring until manifest equality and fingerprint stability are proven.

---

# 15. Phase 8 — Implement AS85 at the actual Gateway boundary

Current gap:

Today the logical flow is approximately:

```text
Context
→ execution_profile_id
→ submit_execution_request()
```

Change it to:

```text
1 Context composition identity
2 resolve canonical composition
3 resolve ExecutionProfile
4 resolve exact provider surface
5 freeze provider capability/evidence result
6 resolve RoleManifest
7 qualify eligible instances
8 create/freeze AgentAdmission
9 persist admission identity/fingerprints
10 submit Gateway execution request
11 AS101 chooses exact instance among eligible candidates
```

---

## 15.1 Preserve provider boundary

`providers_api.py` already exposes the intended read boundary for provider capability/surface information.

Evolve:

```text
read_provider_capability_evidence(...)
read_session_surface_resolution(...)
```

towards the canonical typed result.

Do not make Agents read:

```text
ProviderDescriptor
provider YAML
adapter_ref
session surface declaration internals
```

directly.

---

## 15.2 Eligible instance qualification

Capability admission happens before AS101.

AS101 receives:

```text
eligible instance IDs
```

and considers runtime scheduling/capacity/exact source/model choice.

AS101 must never need code resembling:

```python
if candidate.provider_supports("turn.steer"):
```

If it does, admission is incomplete.

---

## 15.3 Persistence

Persist enough immutable information with the execution request/Work to reconstruct the admission decision exactly after restart.

At minimum identify:

```text
Agent config fingerprint
RoleManifest fingerprint
ExecutionProfile fingerprint
exact surface ref/version identity
resolved capability/evidence fingerprint
eligible instance IDs
```

Use an existing typed request/persistence contract where possible.

Do not dump this into an indefinitely growing arbitrary metadata dictionary merely because `metadata` is easy.

---

## 15.4 Retry rule

Retry of the same admitted Work:

```text
uses frozen admission
```

It does not:

```text
re-read provider config
re-probe provider
re-resolve role capabilities
change candidate semantics
```

A deliberately created successor generation may resolve again.

That is a different operation.

---

## Focused tests

At least:

```text
required capability supported → request accepted
required capability unsupported → admission rejected
required capability unproven → admission rejected with distinct reason
provider unavailable → admission rejected distinctly
adapter failure → internal domain error, not unsupported
candidate set filtered before AS101
AS101 only sees eligible candidates
retry reuses admission
restart reloads identical admission
fingerprints remain stable
```

---

# 16. Phase 9 — Continue AS86–AS93 on the frozen target

Reconcile precise current plan numbering locally, but the dependency direction should remain:

## AS86

System prompt comes from frozen canonical composition.

No provider/session restart can silently pull a changed prompt into existing Work.

## AS87

Request-scoped MCP/materialisation should use admitted canonical capability results.

No capability resolver inside MCP configuration.

## AS88

Same-generation session reuse should compare exact compatibility.

Likely include:

```text
Agent config
RoleManifest
ExecutionProfile
exact surface
runtime/materialisation fingerprint
```

`provider_id == codex` is nowhere near sufficient.

## AS89

Incompatible runtime change creates an explicit successor generation.

Do not silently substitute:

```text
Codex App Server
↔
Codex ACP
```

because provider IDs match.

## AS92/AS93

Reconnect/persisted runtime identity should reuse canonical session facts and binding identity.

Do not introduce another:

```text
ReconnectCapability
SessionResumeCapability
PersistentSessionCapability
```

namespace.

---

# 17. Phase 10 — AS96/AS97/AS98 provider proofs

Once the model exists, provider-specific proof work should **populate it**, not modify it ad hoc.

Conceptually every proof produces:

```text
CapabilitySupport
+
typed surface facts
+
Evidence
```

Examples:

```text
Pi proof
OpenCode ACP proof
Codex ACP bridge/proof
```

If a proof demonstrates absence:

```text
UNSUPPORTED
```

If documentation suggests support but the exact environment is not validated:

```text
UNPROVEN
```

Do not introduce:

```text
CodexCapabilityEvidence
PiRuntimeCapability
OpenCodeFeatureFlag
```

unless a provider-internal implementation genuinely needs such a private type.

---

# 18. Phase 11 — Public projection and AS102

Build one sanitisation boundary before canonical capability/surface state leaves core components.

Allowed public concepts may include:

```text
CapabilityId
support/outcome
safe surface identity
safe version identity
safe facts needed by consumer
public evidence identity/status
```

Never expose:

```text
adapter_ref
Python module reference
command
native CLI switch
private path
native event name
raw protocol payload
credentials
private endpoint
callable
```

---

# 19. Phase 11B — Fix Standard Agents

Current projector:

Replace raw:

```python
project_agent(composition: dict[str, Any])
```

with a typed resolved input.

The exact required stage depends on Standard Agents semantics.

If Standard Agents needs exact model identity:

```text
input = BOUND target
```

If it does not:

```text
input = RESOLVED/ADMITTED target
```

The projector itself must not:

```text
choose an instance
probe provider capabilities
interpret profile fallback order
resolve a provider surface
```

There remains **one projector**.

No:

```text
PortableStandardAgent
BoundStandardAgent
```

parallel semantic representations.

---

# 20. Phase 12 — Delegation, MCP, ACP, A2A, ASA

---

## 20.1 AS94 delegation

Rewrite stale AgentTask/AgentJob language around:

```text
parent Work
    │
    ▼
child Work
```

The Gateway already exposes this direction.

Then capability admission determines whether the chosen exact harness can perform the required native delegation mechanism.

```text
native required operation proven
    → provider adapter performs it

not supported/proven
    → admission/operation unsupported
```

Do not implement a generic hidden AUDiaGentic subagent execution fallback merely to make the capability appear supported.

---

## 20.2 MCP

Consolidate MCP responsibilities into explicit surfaces/owners:

```text
configuration
runtime
delegation
administration
```

If the old generic Gateway MCP endpoint remains purely because several earlier concerns accumulated there, migrate each concern to its correct owner and remove the generic compatibility surface.

---

## 20.3 ACP

ACP is an adapter/projection/transport mechanism over canonical Agent/Work/session/capability state.

It does not acquire:

```text
ACPAgent
ACPTask store
ACP session authority
ACP capability namespace mirroring canonical IDs
```

unless the ACP protocol itself requires a transient protocol representation.

---

## 20.4 A2A

Same rule.

A2A may project:

```text
Agent identity
skills/capabilities
Work/task lifecycle
messages/results
```

but the durable authority stays in AUDiaGentic Context/Work/Gateway.

---

## 20.5 ASA

ASA consumes the resolved/bound target through one projector.

It does not cause the system to create a second “standard” Agent authority.

---

# 21. Phase 13 — AS104 policy only after evidence exists

Do not add speculative policy during taxonomy construction.

Once real execution proves a need, a minimal policy layer may distinguish:

```text
required
allowed
denied
```

Do not add:

```text
preferred
recommended
optional-preferred
fallback
priority-weighted
```

until a concrete use case demands them.

In particular, do not transform AS101 instance fallback candidates into ASA/provider capability fallback semantics.

---

# 22. Required STOP / PIVOT rules

Implementation agents should treat these as hard gates.

| Trigger                                                                         | Required action                               |
| ------------------------------------------------------------------------------- | --------------------------------------------- |
| New capability ID contains provider/harness name                                | STOP — abstraction is likely wrong            |
| Same fact is authored in two config blocks                                      | STOP — choose one authority                   |
| New type is losslessly convertible to an existing type                          | STOP — test whether they are the same concept |
| Agents needs `if provider_id == ...`                                            | STOP — provider behaviour leaked upward       |
| Public model requires `adapter_ref`, command, native endpoint or native payload | STOP — private mechanism leaked               |
| Adapter/config/probe exception becomes unsupported                              | STOP — restore failure semantics              |
| AS101 inspects semantic capabilities                                            | STOP — admission is incomplete                |
| Documented provider feature lacks exact validation                              | Keep `UNPROVEN`                               |
| Protocol adapter wants its own durable Work/task/session store                  | STOP — authority is leaking                   |
| Compatibility path has zero callers                                             | Delete it in that slice                       |
| New migration proposes indefinite old+new aliases                               | STOP — finish destructive cutover             |
| Fingerprint changes because of timestamp/order/prose                            | STOP — fingerprint scope is wrong             |
| State machine is proposed for a pure predicate                                  | STOP — use a strategy/function                |
| Generic `facts: dict[str, Any]` grows                                           | STOP — define a typed fact block              |
| Central `if family == ...` begins growing                                       | STOP — use family polymorphism                |
| Missing harness feature causes generic Agent emulation proposal                 | STOP for this migration                       |

---

# 23. Per-slice working procedure

Every implementation slice should follow the same pattern.

## Before edit

```bash
git status --short

git grep ... # target old symbol
```

Write down:

```text
authority before
authority after
symbols deleted
symbols introduced
```

If two authorities remain after the slice, the slice is incomplete.

---

## Implement

Prefer:

```text
consumer migration
→ new/canonical path
→ tests
→ old path deletion
```

in the same slice.

Avoid:

```text
introduce new path
→ preserve old path indefinitely
→ add compatibility conversion
→ clean up "later"
```

That is how the current duplication accumulated.

---

## Focused validation

Run tests around modified components first.

The current test tree already has coverage around:

```text
Agents definitions/configuration
roles
capabilities
Context/Work
Gateway dispatch
Gateway capacity/recovery
session binding/resume
Standard Agents
ACP
A2A
provider descriptor loading
capability catalogue
session surfaces
surface resolution
inventory conformance
Foundation transition/error machinery
```

---

## Structural validation

```bash
ruff check src tests
pyright
git diff --check
```

Project configuration already defines these development tools and Python 3.11 baseline.

---

## Slice exit

```bash
git status --short
git diff --stat
git diff
```

Then rerun the relevant zero scan.

Commit only when the old representation is gone where the slice says it should be gone.

---

# 24. Major-gate validation ladder

After Phases:

```text
2
6
8
12
```

run:

```bash
python tests/run_all.py --fast
```

The repository's test runner already handles grouping/isolation; do not invent another migration runner.

At the final gate run the consolidated Docker suite exactly as documented in:

```text
tests/TESTING.md
```

---

# 25. Final architecture zero-scans

These should return no production hits except explicitly documented migration fixtures where one is intentionally retained.

```bash
git grep -nE \
  'components\.agent_jobs|AgentTask|AgentTaskFactory' \
  -- src tests || true

git grep -nE \
  'role_api|agent_definition_api|execution_profile_api' \
  -- src tests || true

git grep -n \
  'CapabilityRequirementId' \
  -- src tests || true

git grep -n \
  'ProviderCapabilityFact' \
  -- src tests || true

git grep -n \
  'CapabilityVocabulary' \
  -- src tests || true

git grep -nE \
  'SessionMappingCapabilities|SessionMappingCapability' \
  -- src tests || true

git grep -nE \
  'session_surfaces|harness_observability' \
  -- src tests || true

git grep -nE \
  'provider_id *==|if .*provider_id' \
  -- src/audiagentic/components/agents || true
```

For old `_families.yaml` compatibility:

```bash
git grep -n '_families.yaml' -- src tests || true
```

Delete its fallback only after proving no supported external configuration contract depends on it.

---

# 26. Final behavioural gates

The migration is not complete solely because stale symbols disappear.

Tests must prove:

### Configuration

```text
one mapping-key identity authority
immutable authored configuration
CAS/replacement is the mutation path
unknown/conflicting identity fails
```

### Capability

```text
one CapabilityId namespace
Role uses canonical ID
surface uses canonical ID
RoleManifest contains canonical support subset
facts are not capability aliases
mechanisms are not capability aliases
```

### Evidence

```text
one provider→Agents evidence boundary
exact surface evidence
UNSUPPORTED != UNPROVEN != UNAVAILABLE
unexpected failure raises
cause preserved
```

### Admission

```text
capabilities resolved before AS101
eligible candidates frozen
AS101 binds only qualified candidates
retry reuses admission
restart preserves admission exactly
```

### Sessions

```text
reuse requires exact compatibility
surface identity participates
successor generation explicit
resume cannot silently change execution mechanism
```

### Protocols

```text
ACP has no second durable authority
A2A has no second durable authority
ASA has no second Agent authority
public output is sanitised
```

### Errors

```text
registered public error identities only
actionable stage/context/remediation
no silent provider/config/admission failures
```

---

# 27. Desired final ownership map

```text
                         FOUNDATION
                 ┌────────────────────────┐
                 │ errors                 │
                 │ transitions/workflows  │
                 │ interactions           │
                 │ common semantic IDs    │
                 │ transport primitives   │
                 └───────────┬────────────┘
                             │
            ┌────────────────┴─────────────────┐
            │                                  │
            ▼                                  ▼
          AGENTS                            PROVIDERS
   ┌────────────────────┐          ┌─────────────────────────┐
   │ AgentDefinition    │          │ capability catalogue    │
   │ PromptDefinition   │          │ provider declarations   │
   │ Role               │          │ exact runtime surfaces  │
   │ ExecutionProfile   │          │ facts/evidence          │
   │ Context            │          │ private mechanisms      │
   │ Work               │          │ session implementation  │
   │ admission          │          └────────────┬────────────┘
   └──────────┬─────────┘                       │
              │                                 │
              └──────────────┬──────────────────┘
                             ▼
                    RESOLVED TARGET
                             │
                             ▼
                        ADMISSION
                             │
                             ▼
                      AS101 BINDING
                             │
                             ▼
                       MATERIALIZATION
                             │
               ┌─────────────┼──────────────┐
               ▼             ▼              ▼
            Gateway         ACP/A2A         ASA
```

The architectural test is simple:

> For any piece of information, we should be able to point to exactly one canonical owner and explain every other appearance as either an immutable reference, resolved evidence, operational state, or projection.

If we cannot do that, the migration has created another mirror.

---

# 28. Recommended commit/slice boundaries

Keep these independently revertible.

```text
1  refactor(errors): make provider resolution failures explicit
2  refactor(agents): remove legacy model APIs
3  refactor(agents): remove agent-jobs compatibility authority
4  refactor(config): freeze canonical agent projections
5  refactor(session): remove duplicate session support representations
6  refactor(capabilities): introduce canonical capability identity
7  refactor(providers): converge runtime surface configuration
8  refactor(providers): replace mechanism branching with decoders
9  refactor(providers): make exact surface resolution typed
10 refactor(agents): resolve roles from canonical capability support
11 refactor(gateway): freeze admission before dispatch
12 refactor(session): bind reuse and resume to frozen admission
13 refactor(providers): populate capability evidence from provider proofs
14 refactor(protocols): expose sanitized canonical projections
15 refactor(delegation): execute parent Work to child Work
16 refactor(policy): add evidence-driven capability policy if required
```

Do not combine destructive compatibility removal and a large provider schema redesign into one giant commit.

---

# 29. The first implementation sequence to actually execute

If an implementation agent is starting now, give it only these slices initially:

```text
A. Phase 0 inventory
B. Phase 1 AS72
C. Phase 2.1 legacy model API removal
D. Phase 2.2 AgentDefinition/ExecutionProfile immutability
E. Phase 2.3 agent_jobs destructive classification/removal
F. full --fast gate
G. Phase 3 concept-equivalence audit
```

**Stop there.**

Review the resulting tree and the Phase 3 equivalence table before allowing the agent to implement the canonical `CapabilityId`.

That checkpoint matters because the exact final capability/session taxonomy depends on what remains after compatibility removal.

Trying to implement Phases 4–8 in one autonomous run would recreate exactly the modelling problems this migration is meant to remove.

---

# 30. Final definition of done

The migration is complete when:

```text
one canonical Agent configuration authority
one canonical capability identity
one provider runtime-surface authority
one capability/evidence path
one admission decision
one exact AS101 binding
one session identity model
one Work lifecycle authority
one public sanitisation boundary
```

and:

```text
agent_jobs is gone
old model APIs are gone
CapabilityRequirementId is gone
ProviderCapabilityFact is gone
duplicate session-support model is gone
old runtime-surface/observability dual configuration is gone
capability resolution no longer accepts Any
provider behaviour has not leaked into Agents
AS101 contains no capability policy
protocols own no duplicate durable execution state
unexpected failures are never reported as unsupported
```

with:

```bash
ruff check src tests
pyright
python tests/run_all.py --fast
# consolidated Docker suite from tests/TESTING.md
git diff --check
```

all passing.

That is the point at which ACP, A2A and Standard Agents are genuinely sitting on top of the refactored AUDiaGentic execution platform rather than coexisting beside several generations of its old model.
