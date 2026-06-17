# foundation/workflow/invocation/

Executable workflow-step runtime.

## Intent

Turn declarative or constructed workflow steps into ordered execution with consistent result models.

## Capabilities

- Define invocation result models.
- Run step sequences and aggregate outcomes.
- Provide reusable step types used by dependency installers and other component workflows.

This area executes workflows. It does not decide domain-specific state propagation rules.
