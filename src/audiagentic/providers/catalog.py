"""Compatibility shim for provider model catalog helpers."""
from audiagentic.config.provider_catalog import (  # noqa: F401
    build_model_catalog,
    catalog_is_stale,
    catalog_model_ids,
    read_model_catalog,
    runtime_catalog_path,
    runtime_catalog_root,
    validate_model_catalog,
    write_model_catalog,
)
