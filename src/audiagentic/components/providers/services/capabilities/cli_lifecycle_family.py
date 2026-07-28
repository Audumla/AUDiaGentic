"""CLI-lifecycle automation family.

Family declaration is in _families.yaml (config-based, PC01).
Handler wiring is in automation_registry._REGISTRARS.
"""

from __future__ import annotations

FAMILY_ID = "cli-lifecycle"

__all__ = ["FAMILY_ID"]
