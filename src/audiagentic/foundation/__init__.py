"""Foundation building blocks.

Core primitives used across components: contracts, references, templates,
paths, config, lifecycle, logging, observability, toolchains, workflow engine,
event bus, features, interaction storage, system utilities, and time helpers.
"""
from audiagentic.foundation.config.refs import resolve_ref
from audiagentic.foundation.i18n import I18n, _t_err
from audiagentic.foundation.templates import render_template

__all__ = [
    "I18n",
    "_t_err",
    "render_template",
    "resolve_ref",
]
