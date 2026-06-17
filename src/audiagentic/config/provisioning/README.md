# config/provisioning/

Default provisioning config shipped with package.

## Intent

Provide baseline runtime settings before user-global or project-local overrides apply.

## Areas

- `foundation/` logging defaults.
- `harness/` generic and harness-specific runtime defaults.
- `rig/` embedded model rig profiles and ports.

These files feed layered config loaders in `runtime/config/` and should describe sane portable defaults, not machine-specific state.
