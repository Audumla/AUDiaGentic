# planning/

## Purpose

The planning component is a configurable workflow and document-output engine. It manages planning items, their relationships, their state transitions, and the generated documents that represent those items.

The important architectural direction is that planning code should not know the project's planning vocabulary. Names such as request, spec, task, work package, standard, ready, done, archived, or particular reference fields are configuration data. The code should operate on configured kinds, configured fields, configured workflows, configured lifecycle actions, and configured document templates.

This lets the same engine support a different planning model without changing Python code. A project should be able to rename kinds, add or remove kinds, change states, alter reference fields, change default references, and adjust document structure from configuration.

## Ownership

The planning component owns:

- Creation, reading, editing, deletion, and indexing of planning items.
- Configured item kinds and their file locations.
- Configured state machines and state transitions.
- Configured lifecycle actions such as archive, restore, or project-specific equivalents.
- Configured cascades between related items.
- Configured workflow actions that create or update groups of items.
- Configured reference fields, reference targets, and inherited references.
- Generated document bodies, templates, required sections, and validation rules.
- MCP and CLI surfaces that expose generic planning operations.

The planning component does not own:

- Agent execution or provider dispatch.
- Runtime job orchestration.
- Release automation.
- Knowledge indexing outside planning documentation.
- Hardcoded project-specific planning policy.

## Core Principle

Configuration is the source of planning behavior. Code is the generic interpreter.

Code may implement mechanics:

- Load and validate configuration.
- Read and write frontmatter documents.
- Generate IDs using configured prefixes and counters.
- Apply state transitions.
- Apply configured cascades.
- Validate references against configured target kinds.
- Render configured templates.
- Resolve configured effective references.
- Execute configured workflow actions.

Code should not embed business policy:

- It should not decide that a particular kind must exist.
- It should not decide that a particular state name means complete or terminal.
- It should not decide which reference fields belong to which kind.
- It should not decide which child kinds cascade from which parent kind.
- It should not decide document sections by item type.
- It should not special-case standards, tasks, specs, packages, or any current project kind.

## Configuration Files

### planning.yaml

`planning.yaml` is the structural source of truth.

It defines configured kinds, directories, ID prefixes, counter files, base fields, optional fields, reference fields, reference targets, lifecycle actions, lifecycle state sets, workflow action definitions, queue defaults, and core creation rules.

This file answers questions such as:

- What kinds exist?
- Where is each kind stored?
- What ID prefix and counter file does each kind use?
- Which reference fields exist?
- Which target kinds can each reference field point to?
- Which lifecycle actions exist?
- Which states are initial, active, blocked, complete, or terminal?
- What cascades happen when an action is applied?
- What configured workflow actions create or link items?

### workflows.yaml

`workflows.yaml` defines valid state machines.

It defines the allowed states and transitions for each configured kind and workflow. `planning.yaml` defines semantic state sets, while `workflows.yaml` defines transition validity.

This separation matters. A state name is project vocabulary. A semantic set such as initial, active, complete, blocked, or terminal is engine vocabulary. The engine uses the semantic set; the config decides which states belong to it.

### profiles.yaml

`profiles.yaml` defines creation profiles, guidance levels, document templates, relationship rules, required sections, state-section requirements, and default references.

It answers questions such as:

- Which profile should create which related items?
- What defaults should be applied during item creation?
- What document body should a kind start with?
- What sections are required or suggested?
- What reference defaults should be added to each kind?
- Which relationship rules should validation enforce?

`default_references` is intentionally generic. It maps kind and field to default IDs. It does not assume standards are special in code.

### state_propagation.yaml

`state_propagation.yaml` defines event-driven propagation rules.

This is for state logic that depends on conditions across related items. It is separate from lifecycle cascades because propagation can be rule-based, conditional, and event-driven. Lifecycle cascades are direct action effects configured under lifecycle actions.

### documentation.yaml

`documentation.yaml` defines documentation surfaces and collections.

This replaces hardcoded standard/support managers. Documentation resources are configured collections, not separate Python manager types.

### automations.yaml

`automations.yaml` defines configured automation hooks and behavior. Automation is policy configuration; the engine should only interpret it.

## Runtime Services

The app layer is split into services so the API facade does not become a hardcoded policy blob.

Important service boundaries:

- `ItemCreatorService` handles generic item creation from configured kind rules.
- `FrontmatterBuilder` builds fields from config, references, defaults, state, and workflow.
- `PolicyService` handles generic validation policies, including configured reference validation.
- `LifecycleService` handles generic lifecycle actions, state transitions, metadata mutation, and cascades.
- `PlanningSupersedeService` handles planning-domain supersede behavior, separate from generic lifecycle mechanics.
- `WorkflowActionsService` and `WorkflowActionExecutor` execute configured multi-item actions.
- `RelationshipService` manages reference mutations and relationship list merging.
- `QueueService` exposes configured next-item selection.
- `ContentService`, `ItemReaderService`, `MaintenanceService`, and `EventService` handle document content, reads, maintenance, and events.

The goal is not to over-engineer many tiny abstractions. The goal is to keep concerns separated enough that config policy does not leak into generic mechanics.

## Lifecycle And Cascades

Lifecycle actions are configured operations that may change state, mutate metadata, emit events, and cascade to related items.

Examples of lifecycle action categories include archive, restore, supersede, freeze, cancel, or any project-specific equivalent. The engine should not care about the action name. It should read the action definition from config.

Cascade rules belong in lifecycle action config. A cascade says that when an action is applied to a parent kind, related child kinds should transition to configured target states. The cascade executor should use configured relationships and configured child kind mappings.

Archive should be treated as one configured lifecycle action, not a privileged hardcoded workflow. It may still be an important capability, but it should be important because config defines it that way.

Restore is similar. If restore has special constraints, those constraints should be represented as lifecycle action config or validation policy, not scattered string checks.

## State Propagation

State propagation is separate from lifecycle cascades.

Use lifecycle cascades when applying an action directly causes related item transitions.

Use propagation rules when a state change should trigger conditional logic, such as parent completion based on child states, blocking relationships, or event-driven updates.

Rules must not hardcode current project state names. They should reference configured states, configured state sets, configured fields, or configured rule parameters.

## References

References are config-defined fields with config-defined target kinds.

The engine should validate references by checking that an item's kind is included in the configured target kinds for that field. It should not assume the first target is the only valid target, and it should not infer field meaning from field names.

Effective references are also generic. The configured default reference field may currently point at standards, but that is project policy. The generic operation is resolving effective references for a field.

MCP exposes this as `tm_refs`, not a standard-specific operation.

## Workflow Actions

Workflow actions are configured multi-step operations.

They may create items, set fields, attach references, update parent relationships, and return named results. Code executes the configured action; config defines what the action means.

MCP exposes generic grouping through `tm_group`. The current project may use that to create a work package from a plan and tasks, but the tool name should not assume that shape.

## Supersede

Supersede is planning-domain behavior, not generic lifecycle infrastructure.

Generic lifecycle can transition an old item to a configured state. Planning supersede additionally detects configured refinement source patterns, links old and new items, writes configured metadata fields, and annotates the old item body.

That behavior lives in `PlanningSupersedeService` as a planning-domain service. The generic lifecycle service should not know what supersede means.

## Schemas

Schemas should validate configuration shape, not hardcode project policy.

Good schema behavior:

- Require structural sections that the engine needs.
- Require fields needed to interpret config safely.
- Allow configured kinds and states to be arbitrary strings.
- Validate generic lifecycle action structure.
- Validate generic workflow action structure.
- Validate generic reference configuration.

Bad schema behavior:

- Hardcoding kind names.
- Hardcoding state names.
- Hardcoding reference field names.
- Embedding planning-domain supersede fields directly into generic lifecycle schema.
- Keeping deprecated config files or aliases after the migration point has passed.

Domain-specific extensions should sit under explicit extension blocks. The generic schema can allow extensions, while the owning domain service validates the fields it needs.

## MCP And CLI Surface

Public tools should prefer generic names:

- `tm_create` creates any configured kind.
- `tm_list` lists configured kinds.
- `tm_get` reads configured items.
- `tm_edit` mutates fields and sections.
- `tm_relink` updates configured reference fields.
- `tm_group` runs configured grouping behavior.
- `tm_refs` resolves configured effective references.
- `tm_docs` reads configured documentation collections.

Avoid type-specific public tools; prefer operation names that work for any configured kind.

## Greenfield Portability

The greenfield config portability tests are the guardrail for this architecture.

Those tests intentionally use different kind names, state names, workflows, references, lifecycle actions, cascades, and default reference behavior. If a greenfield configuration fails because code expects request/spec/task/wp/standard, the code is still too hardcoded.

When adding new planning behavior, add or update a greenfield test where practical. It should prove the feature works with different names, not just with the default project vocabulary.

## Extension Workflow

When changing planning behavior:

1. Decide whether it is generic engine behavior or project/domain policy.
2. If it is policy, put it in config.
3. If schema support is needed, make the schema generic.
4. Add config accessors only when they expose generic concepts.
5. Keep domain-specific services separate from generic services.
6. Validate with normal planning tests and greenfield portability tests.
7. Scan for hardcoded kind names, state names, and reference fields.

## Current Direction

The refactor is moving planning from a monolithic, planning-vocabulary-specific API toward a generic workflow-state engine with document output.

The desired end state:

- Few files, but clear service boundaries.
- Slim config, with derived values where possible.
- No duplicated config values where code can derive them.
- No legacy compatibility shims.
- No hardcoded planning vocabulary in engine code.
- Archive implemented as a configured lifecycle action with generic cascade behavior.
- MCP and CLI tools named after generic operations, not project-specific types.
