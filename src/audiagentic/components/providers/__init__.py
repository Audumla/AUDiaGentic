"""Provider registry — importing this package registers built-in providers."""

from __future__ import annotations

from . import adapters
from .services.recipe_steps import register_provider_steps

# Register provider-layer recipe step types (managed-mcp, …) into the foundation
# step factory so recipes can materialize provider config through the shielded
# managed families. Idempotent.
register_provider_steps()

__all__ = ["adapters", "register_provider_steps"]
