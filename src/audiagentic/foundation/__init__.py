"""Foundation building blocks.

Core primitives used across components: contracts, references, templates,
paths, config, lifecycle, logging, observability, toolchains, workflow engine,
event bus, features, interaction storage, system utilities, and time helpers.
"""
from audiagentic.foundation.refs import resolve_ref
from audiagentic.foundation.templates import render_template

__all__ = [
    "render_template",
    "resolve_ref",
]
