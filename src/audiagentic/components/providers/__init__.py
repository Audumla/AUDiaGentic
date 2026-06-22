"""Provider registry — importing this package registers built-in providers."""

from __future__ import annotations

from . import adapters

__all__ = ["adapters"]
