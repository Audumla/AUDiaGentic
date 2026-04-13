"""AUDiaGentic: Agentic workflow orchestration and execution platform.

Top-level package for the AUDiaGentic system. Domain layout:

  foundation/        — shared contracts and configuration (base layer)
  planning/          — planning workflows and task management
  execution/         — job orchestration and state machines
  interoperability/  — external provider integrations and protocols
  runtime/           — lifecycle management and durable state persistence
  release/           — release governance, audit, and change ledger
  channels/          — operator-facing surfaces (cli, vscode)
  knowledge/         — optional knowledge management capability (deferred)
"""

__version__ = "0.1.0"
