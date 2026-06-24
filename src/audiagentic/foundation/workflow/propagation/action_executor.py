"""Action execution for propagation state transitions."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Execute propagation actions and return suggested transitions."""

    def __init__(self, workflow_config: dict[str, Any]) -> None:
        self._workflow_config = workflow_config

    def execute(
        self, action_entry: dict[str, Any], item_id: str, state_rules: dict[str, Any]
    ) -> list[tuple[str, str, str]]:
        action_name = action_entry.get("action")
        if not action_name:
            return []
        action_config = self._workflow_config.get("actions", {}).get(action_name, {})
        if not action_config.get("enabled", True):
            return []
        logic = action_config.get("logic")
        if not logic:
            logger.warning("Action %s has no logic implementation", action_name)
            return []
        try:
            return logic(self, item_id, action_entry, state_rules)
        except Exception:
            logger.error("Action %s failed", action_name, exc_info=True)
            return []
