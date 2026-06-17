# foundation/system/

Host process and machine-level helpers.

## Intent

Wrap low-level OS interactions that higher layers reuse for startup coordination and process probing.

## Capabilities

- Startup locks and process lifecycle helpers.
- Cross-platform probes for binaries or host state needed by runtime services.

Keep business logic out of this layer. It should stay thin, predictable, and safe for reuse.
