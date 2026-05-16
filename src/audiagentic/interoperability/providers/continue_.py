"""Python-safe import alias for the Continue provider package."""

from __future__ import annotations

import importlib

adapter = importlib.import_module(".continue.adapter", __package__)
descriptor = importlib.import_module(".continue.descriptor", __package__)

__all__ = ["adapter", "descriptor"]
