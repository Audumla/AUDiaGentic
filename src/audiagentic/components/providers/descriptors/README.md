# components/providers/descriptors/

Provider descriptor model, registry, and YAML loader.

## Intent

Define uniform metadata contract for every provider adapter. Provider descriptors
are declared in YAML under `config/providers/*.yaml` and loaded via the
`DescriptorSpec` mechanism in `spec.py`.

## Files

- `base.py` — `ProviderDescriptor` dataclass and nested types (permissions, agent files, etc.)
- `registry.py` — Public registry API: `register`, `get_descriptor`, `all_descriptors`,
  `canonical_provider_ids`, `provider_alias_map`, `interrogate`. Composes
  `foundation.registry_utils.Registry[ProviderDescriptor]` internally.
- `loader.py` — YAML loader: `load_provider_descriptor`, `load_providers_from_directory`,
  `PROVIDER_SPEC` field specification. Uses the generic `foundation/descriptors` mechanism.
- `feature_mapping.py` — Derives implementation-scoped features from provider descriptors.

## YAML descriptor authoring

Provider descriptors live in `config/providers/<provider_id>.yaml`. Each file is
loaded by `loader.py` which resolves dotpath references using the colon convention
(`module:attr`). The `PROVIDER_SPEC` declares the field map.

### Dotpath convention

Callable references use colon syntax: `audiagentic.components.providers.adapters.claude.catalog:_fetch_claude_catalog`

The single canonical resolver is `foundation/descriptors/resolver.py:resolve_ref()`.

### Adding a new provider

1. Create `config/providers/<id>.yaml` with the required fields (`provider_id`, `display_name`).
2. If the provider needs custom hooks (probe, catalog fetch, LSP), create
   `adapters/<id>/hooks.py` or `adapters/<id>/catalog.py` with top-level functions.
3. Reference hooks via colon dotpath in the YAML file.
4. The adapter package is auto-discovered via `pkgutil.iter_modules()` — no manual registration needed.

## Architecture notes

- Foundation registries (`foundation/components/`, `foundation/features/`) are out of scope.
- Provider registry composes `foundation.registry_utils.Registry[T]` (PD08 D2; consolidated
  from the former `DescriptorRegistry` in 2026-07). Step specs are built by
  `foundation.workflow.invocation.from_spec.build_step_from_spec` — workflow owns its
  own YAML deserializer.
- Requester-specific provider matrices remain in their owning component configs.
