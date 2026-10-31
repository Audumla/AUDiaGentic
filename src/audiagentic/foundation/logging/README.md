# foundation/logging/

Central logging and audit configuration.

## Intent

Provide one place to configure stdlib logging, structured output, correlation context, and optional AI audit logs.

## Capabilities

- Read the `logging` section of the resolved settings (packaged defaults, user, project); `AUDIAGENTIC_LOG_LEVEL` overrides the level.
- Build console/file logging setup.
- Carry correlation IDs through log context.
- Support diagnostic logs and optional redacted AI audit logs.

Agents usually enter here when changing log shape, precedence rules, or audit retention behavior.
