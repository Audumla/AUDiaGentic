# foundation/toolchains/

External dependency detection and recipe loading.

## Intent

Describe host tool dependencies once, then let components reuse the same install/probe workflow model.

## Capabilities

- Detect available package managers and common tooling such as `uv`.
- Load dependency probe definitions and install/uninstall workflows from `toolchains.yaml`.
- Provide platform-aware helpers for system package recipes.

Components such as coding LSP and source control depend on this layer for host bootstrap.
