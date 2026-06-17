"""AUDiaGentic: Agentic workflow orchestration and execution platform.

Top-level package for the AUDiaGentic system. Domain layout:

  foundation/   — shared contracts, event bus, and the component framework (base layer)
  components/   — core and optional components (project, session, providers, ledger, ...)
  runtime/      — lifecycle management, harness, and durable state persistence
  config/       — component descriptors and provisioning configuration
"""

__version__ = "0.1.1"
