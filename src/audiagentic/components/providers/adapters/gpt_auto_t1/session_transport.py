"""Re-export the shared gpt-auto session transport builder for gpt-auto-t1.

See ``adapters/gpt_auto_t1/__init__.py`` -- this is an alias, not a separate
implementation.
"""

from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    build_session_transport,
)

__all__ = ["build_session_transport"]
