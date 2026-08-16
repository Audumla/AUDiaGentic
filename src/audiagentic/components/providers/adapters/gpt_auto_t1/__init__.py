"""gpt-auto-t1: dedicated GP05 test-project alias of the gpt-auto adapter.

Same CDP browser-automation implementation as gpt-auto (shared runtime,
PersistentChat, snapshot machinery); only the provider settings file
(project-url) differs. This package exists solely so the adapter-hook
convention (``adapters/<provider_id>/session_transport.py``) can resolve a
transport builder for this provider_id without any dispatcher edit.
"""

from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    build_session_transport,
)

__all__ = ["build_session_transport"]
