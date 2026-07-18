# Resource Consumption Contract

## Intended consumers

- provider registry service;
- harness launcher and configuration projector;
- capability gateway;
- scheduler and policy engine;
- telemetry service;
- UI and diagnostics;
- validation and compatibility probes.

## Rules

1. Consumers must tolerate unknown fields and unsupported capabilities.
2. Missing capability records mean `unknown`, not `false`.
3. `unsupported` requires evidence or a named reason.
4. Runtime probes may override stale documented facts, but must retain both observations.
5. Credentials are referenced, never stored in this resource.
6. Version-sensitive facts must carry a version scope.
7. Derived values must retain their derivation and inputs.
8. A harness/provider/model combination is uniquely identified by a binding, not by model display name.

## Stable identifiers

Identifiers are lowercase kebab-case. Existing canonical capability IDs in `model/capability-id-taxonomy.md` remain authoritative. Registry aliases exist only for migration and must resolve to one canonical ID.
