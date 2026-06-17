# config/

Packaged defaults shipped with AUDiaGentic.

## Intent

This tree is source-of-truth input for component loading and runtime provisioning before project-local overrides exist.

## Areas

- `components/` component descriptors and packaged skills/config fragments.
- `provisioning/` default runtime config for logging, harnesses, and rig profiles.

Do not treat these files as generated output. They are authored defaults consumed by install/runtime code.
