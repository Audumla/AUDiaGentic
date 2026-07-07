"""Prompt-trigger tag registry — auto-loads all tags on import."""
from .loader import load_all_tags as _load
from .registry import all_tags, get_tag  # noqa: F401

_load()
