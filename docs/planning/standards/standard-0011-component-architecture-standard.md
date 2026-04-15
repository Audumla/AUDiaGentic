---
id: standard-0011
label: Component architecture standard
state: ready
summary: Default standard for architectural design of components in AUDiaGentic-based
  projects, covering clear layering, modularity, config-driven design, and extensibility.
---

# Standard

Default standard for how components in AUDiaGentic-based projects should be structured architecturally. Applies to any new component or significant redesign. Covers dependency direction, module contracts, configuration externalization, and extension point design.

# Source Basis

This standard is derived from established software architecture principles adapted for this repository's Python-based, planning-led, multi-agent context.

Sources:
- [The Twelve-Factor App](https://12factor.net/) — config externalization, dependency isolation, process boundaries
- [Clean Architecture (Robert C. Martin)](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html) — dependency rule, layer isolation, framework independence
- [The Hitchhiker's Guide to Python — Project Structure](https://docs.python-guide.org/writing/structure/) — module organization, separation of concerns
- [The Zen of Python (PEP 20)](https://peps.python.org/pep-0020/) — explicitness, flat over nested, readability
- Repository existing component patterns (planning, knowledge, interoperability)

# Requirements

## Layering

1. Components must define their layers explicitly. Each layer has one responsibility and one direction of dependency. The standard layers for this repository are:

   - **Domain** — core logic, data structures, business rules; no knowledge of infrastructure or transport
   - **Application** — orchestrates domain logic; coordinates use cases; no knowledge of UI, MCP, or storage technology
   - **Infrastructure** — storage, file I/O, external APIs, persistence; depends on domain interfaces, not the reverse
   - **Surface** — MCP tools, CLI entrypoints, HTTP handlers; thin adapters that translate between the transport and the application layer

2. Dependencies must point inward: Surface → Application → Domain. Infrastructure depends on Domain interfaces. Domain must never import from Surface, Application, or Infrastructure.

3. Inner layers must not name or import outer layers. If an inner layer needs a capability from an outer layer, define an interface in the inner layer and inject the implementation from outside.

4. Framework and transport choices are Surface concerns. Domain and Application layers must remain operable without MCP, CLI, or any specific transport being present.

5. A layer boundary is violated when: an import crosses inward-to-outward, a domain object contains file paths or SQL, or a Surface layer contains business logic beyond validation and translation.

## Modularity

6. Each module must have a single, stated responsibility. A module that is hard to name without using "and" is doing too much.

7. Module public APIs must be explicit. Anything not intended for external use should not be importable from the package root. Use `__all__` or keep internal symbols in private submodules.

8. Circular imports are prohibited. If two modules need each other, extract the shared dependency into a third module or invert the dependency via an interface.

9. Bootstrap wiring — connecting components, registering handlers, injecting dependencies — must happen at a defined entry point, not inside domain or application modules. Modules must not self-register or reach for global singletons during import.

10. Shared utilities used across multiple components must live in a dedicated shared module, not be duplicated or inlined per-component.

## Config-Driven Design

**Important: Config-driven design is NOT schema-driven.** Configuration drives behavior at runtime through explicit parameter passing and configuration files. Schema validation is a tool to ensure configuration integrity, NOT the primary driver of component behavior. Components must remain functional even when schema validation is disabled or incomplete.

11. Behavior that varies between environments, deployments, or optional feature sets must be driven by configuration, not by code branches on hardcoded values.

12. Configuration must be loaded at a defined entry point and passed explicitly to components that need it. Components must not read environment variables or config files from within domain or application logic.

13. All configuration must have documented defaults. A component must be operable with no config file present, using documented defaults, unless a config file is explicitly required by the specification.

14. Optional features must be disabled by default and enabled via configuration. The absence of a config key must always produce a safe, minimal behavior.

15. Configuration schema must be versioned or stable. Breaking changes to config shape require migration guidance. Schema validation is optional and should never prevent component operation - components must work with partial or invalid config gracefully.

16. Configuration must not contain secrets inline. Secrets must be injected via environment variables and documented as required external inputs.

17. Components must not hardcode paths to other components' configuration files or resources. The owner component (e.g., planning) is responsible for passing config paths to dependent components (e.g., interoperability). This ensures components remain independent and testable without knowledge of other components' internal structure.

18. Components must not have hardcoded defaults that duplicate configuration. All behavior must be explicitly configured through external config files or passed as parameters. If a config file is missing, the component should either use a minimal safe default (e.g., disabled feature) or fail fast with a clear error. Hardcoded fallback configs create hidden behavior that is hard to audit and violates config-driven design principles.

19. Business logic and rules must be config-driven, not hardcoded. Components should provide pluggable implementations that are referenced by name in configuration files. This allows workflows and behaviors to be changed without modifying code. Rule implementations should live in separate modules and be imported dynamically based on config references.

## Extensibility

19. Extension points — places where behavior is expected to vary or be added by outside code — must be defined explicitly as interfaces, abstract base classes, or documented registration patterns. Implicit extension via monkey-patching or subclassing undocumented internals is prohibited.

20. New implementations of an extension point must be addable without modifying core code. The Open-Closed Principle applies: open for extension, closed for modification.

21. Plugin and adapter registration must use explicit wiring (bootstrap or entry points), not import-time side effects. Components must not discover or register themselves.

22. Python entry points (`pyproject.toml` `[project.entry-points]`) are the preferred mechanism for optional, installable extensions. Use registry patterns (dict or list populated at bootstrap) for in-process optional behavior.

23. Extension interfaces must document: expected inputs, expected outputs, error contract, and whether the extension is called synchronously or asynchronously.

24. Removing or changing an extension interface is a breaking change and must follow the migration standard.

## Event-Driven Architecture

25. Components must not subscribe to events on behalf of other components. Each component is responsible for registering its own event handlers with the event bus. This ensures clear ownership and prevents tight coupling between components.

26. Utility components (e.g., state propagation engine, healing engine) must be passive - they provide methods for calculating or applying changes but do NOT subscribe to events or trigger actions automatically. The owner component (e.g., planning) registers event handlers that call these utilities.

27. The event bus must remain ignorant of specific event types and handlers. It is a generic pub/sub system that matches patterns and dispatches to registered handlers. Event type definitions and handler logic belong in the components that use them.

28. Event bus implementations must be swappable. The event bus protocol (`EventBusProtocol`) defines the interface for publishing and subscribing. Alternative implementations (e.g., RabbitMQ, Kafka) must be able to replace the in-process implementation without modifying component code.

29. Event handlers must be resilient to failures. A failure in one handler must not prevent other handlers from receiving the event. The event bus must isolate handler failures and log errors without crashing the system.

30. Event subscriptions must NOT happen at import time. Components must provide explicit opt-in functions (e.g., `setup_event_subscriptions()`) that are called by the owner component during bootstrap. This prevents unexpected side effects and makes event wiring explicit and testable.

# Default Rules

- If a module import creates a chain longer than three hops, reconsider the structure.
- Prefer passing config and dependencies as arguments over reading from globals or class variables.
- Keep Surface-layer modules thin: validate input, call application layer, format output. No business logic.
- If adding a feature requires modifying a core module rather than adding a new one, reconsider the extension point design.
- Document the intended layer of every new module in its module docstring.
- Flat is better than nested: avoid deep package hierarchies unless there is a clear domain reason.

# Verification Expectations

- Layer dependency direction must be verifiable by import inspection (no outward imports from inner layers).
- Config-driven behavior must be testable with different config values without code changes.
- Components must operate correctly even when schema validation is disabled.
- Extension points must have at least one test that exercises a non-default implementation.
- Bootstrap wiring must be tested end-to-end at least once in the integration test suite.
- Circular import checks should be part of the standard smoke test (e.g., `python -c "import audiagentic"`).

# Non-Goals

- Prescribing specific design patterns (factory, strategy, observer) beyond what the repository already uses.
- Enforcing micro-service or distributed architecture boundaries within a single deployable.
- Replacing project-specific specs for individual component designs.
- Mandating dependency injection frameworks; constructor injection and bootstrap wiring are sufficient.
