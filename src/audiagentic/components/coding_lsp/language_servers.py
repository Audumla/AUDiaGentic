from __future__ import annotations

# LanguageServerEntry moved to providers contracts (MA28). Re-export for
# backwards compatibility during migration; remove this module after all
# callers are migrated.
from audiagentic.components.providers.providers_api import (
    LanguageServerEntry,
)

__all__ = ["LanguageServerEntry"]
