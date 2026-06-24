"""Propagation rule evaluation for state transitions."""

from __future__ import annotations

import logging
from typing import Any

from .parents import find_parents

logger = logging.getLogger(__name__)


class PropagationRuleEvaluator:
    """Evaluate propagation rules and return suggested transitions."""

    def __init__(self, ctx: Any, workflow_config: dict[str, Any], max_depth: int) -> None:
        self.ctx = ctx
        self._workflow_config = workflow_config
        self._max_depth = max_depth

    @property
    def workflow_config(self) -> dict[str, Any]:
        return self._workflow_config

    @property
    def config(self) -> Any:
        return getattr(self.ctx, "config", None)

    def evaluate(
        self,
        item_id: str,
        new_state: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[tuple[str, str, str]]:
        if metadata and metadata.get("healing_fix"):
            return []
        if (metadata or {}).get("propagation_depth", 0) >= self._max_depth:
            logger.warning("propagate() max depth reached")
            return []

        item_view = self.ctx.lookup(item_id)
        if not item_view or not item_view.data:
            return []
        kind = getattr(item_view, "kind", None) or item_view.data.get("kind")
        if not kind:
            return []

        cfg = self._workflow_config
        if not cfg.get("global", {}).get("enabled", True):
            return []
        kind_config = cfg.get("kinds", {}).get(kind, {})
        if not kind_config.get("enabled", True):
            return []

        override = item_view.data.get("propagation", {}) or {}
        if override.get("enabled") is False:
            return []

        state_rules = kind_config.get("state_rules", {}).get(new_state, {})
        rule = state_rules.get("rule", "none")
        target_state = state_rules.get("new_state")
        if not target_state or rule == "none":
            return []

        parents = find_parents(
            self.ctx, item_id, kind_config.get("parent_kind"), kind_config.get("parent_field")
        )
        if not parents:
            return []

        propagations: list[tuple[str, str, str]] = []
        for parent_id, parent_kind in parents:
            if self._apply_rule(item_id, parent_id, new_state, state_rules):
                propagations.append((parent_id, parent_kind, target_state))

        for action_entry in state_rules.get("actions", []):
            propagations.extend(self._execute_action(action_entry, item_id, state_rules))

        return list(dict.fromkeys(propagations))

    def _apply_rule(
        self, child_id: str, parent_id: str, new_state: str, state_rules: dict[str, Any]
    ) -> bool:
        rule = state_rules.get("rule")
        if not rule:
            return False
        rule_config = self._workflow_config.get("rules", {}).get(rule, {})
        if not rule_config.get("enabled", True):
            return False
        logic = rule_config.get("logic")
        if not logic:
            logger.warning("Rule %s has no logic implementation", rule)
            return False
        try:
            return logic(self, child_id, parent_id, new_state, state_rules.get("when"))
        except Exception:
            logger.error("Rule %s failed", rule, exc_info=True)
            return False

    def _execute_action(
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
