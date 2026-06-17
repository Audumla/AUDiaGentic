"""Config-driven state propagation engine.

The engine is a passive utility: it never subscribes to events directly. Hosts
call :meth:`propagate` after a state change to obtain a list of suggested
follow-up transitions, then call :meth:`apply_propagation` to apply them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import healing as _healing
from .log import PropagationLog
from .parents import find_parents
from .propagation_config import load_config, validate
from .workflow_item_api import WorkflowItemAPI

logger = logging.getLogger(__name__)


class StatePropagationEngine:
    def __init__(
        self,
        ctx: WorkflowItemAPI,
        enabled: bool = True,
        config_path: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        if enabled and config_path is None:
            raise ValueError(
                "StatePropagationEngine enabled=True requires config_path. "
                "Either pass config_path or set enabled=False."
            )
        self.ctx: Any = ctx
        self._enabled = enabled
        self._config_path = config_path
        self._workflow_config: dict[str, Any] | None = None
        self._log = PropagationLog(log_path)

    # ------------------------------------------------------------------ public

    @property
    def config(self) -> Any:
        """Host workflow config (kind/state semantics)."""
        return getattr(self.ctx, "config", None)

    @property
    def workflow_config(self) -> dict[str, Any]:
        """Loaded propagation YAML config (lazy)."""
        if self._workflow_config is None:
            self.load_workflow_config()
        return self._workflow_config or {}

    def load_workflow_config(self) -> dict[str, Any]:
        config = load_config(self._config_path if self._enabled else None)
        warnings = validate(config, self._states_for_kind)
        if warnings:
            logger.warning("Config validation warnings: %s", ", ".join(warnings))
        self._workflow_config = config
        return config

    def propagate(
        self,
        item_id: str,
        new_state: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[tuple[str, str, str]]:
        if not self._enabled:
            return []
        if metadata and metadata.get("healing_fix"):
            return []
        if (metadata or {}).get("propagation_depth", 0) >= self._max_depth():
            logger.warning("propagate() max depth reached")
            return []

        item_view = self.ctx.lookup(item_id)
        if not item_view or not item_view.data:
            return []
        kind = getattr(item_view, "kind", None) or item_view.data.get("kind")
        if not kind:
            return []

        cfg = self.workflow_config
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

    def apply_propagation(
        self,
        target_id: str,
        target_state: str,
        source_id: str,
        source_state: str,
        metadata: dict[str, Any],
    ) -> None:
        target_view = self.ctx.lookup(target_id)
        if not target_view or not target_view.data:
            logger.warning("Target item not found: %s", target_id)
            self._record(
                "failed", target_id, target_state, source_id, source_state, metadata,
                reason="target_not_found",
            )
            return

        target_kind = getattr(target_view, "kind", None) or target_view.data.get("kind")
        cfg = self.config
        if cfg is None:
            raise ValueError("State propagation requires Config")

        current_state = target_view.data.get("state", cfg.initial_state(target_kind))

        if current_state == target_state:
            self._record(
                "skipped", target_id, target_state, source_id, source_state, metadata,
                target_kind=target_kind, old_state=current_state,
                reason="already_in_target_state",
            )
            return

        workflow_name = target_view.data.get("workflow")
        current_priority = cfg.state_priority(target_kind, current_state, workflow_name)
        target_priority = cfg.state_priority(target_kind, target_state, workflow_name)
        if target_priority < current_priority:
            self._record(
                "skipped", target_id, target_state, source_id, source_state, metadata,
                target_kind=target_kind, old_state=current_state,
                reason="lower_priority_than_current_state",
            )
            return

        current_depth = metadata.get("propagation_depth", 0)
        if current_depth >= self._max_depth():
            self._record(
                "skipped", target_id, target_state, source_id, source_state, metadata,
                target_kind=target_kind, old_state=current_state, reason="max_depth_reached",
            )
            return

        new_metadata = dict(metadata)
        new_metadata["propagation_depth"] = current_depth + 1
        new_metadata["propagation_source"] = source_id
        new_metadata["propagation_trigger"] = f"{source_id}:{source_state}"

        try:
            self.ctx.state(id_=target_id, new_state=target_state, metadata=new_metadata)
        except ValueError as exc:
            self._record(
                "skipped", target_id, target_state, source_id, source_state, new_metadata,
                target_kind=target_kind, old_state=current_state, reason="invalid_transition",
            )
            logger.debug("Propagation skipped invalid transition for %s: %s", target_id, exc)
            return
        except Exception as exc:
            self._record(
                "failed", target_id, target_state, source_id, source_state, new_metadata,
                target_kind=target_kind, old_state=current_state, reason=str(exc),
            )
            raise

        self._record(
            "success", target_id, target_state, source_id, source_state, new_metadata,
            target_kind=target_kind, old_state=current_state,
        )
        logger.info(
            "Propagated state: %s -> %s triggered by %s (%s)",
            target_id, target_state, source_id, source_state,
        )

    # ---- healing facade ------------------------------------------------

    def validate_hierarchy(self, item_id: str) -> list[dict[str, Any]]:
        return _healing.validate(self, item_id)

    def heal_hierarchy(self, item_id: str, auto_fix: bool = False) -> dict[str, Any]:
        return _healing.heal(self, item_id, auto_fix)

    def apply_healing_fix(self, fix: dict[str, Any]) -> None:
        _healing.apply_fix(self, fix)

    # ---- internals -----------------------------------------------------

    def _apply_rule(
        self, child_id: str, parent_id: str, new_state: str, state_rules: dict[str, Any]
    ) -> bool:
        rule = state_rules.get("rule")
        if not rule:
            return False
        rule_config = self.workflow_config.get("rules", {}).get(rule, {})
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
        action_config = self.workflow_config.get("actions", {}).get(action_name, {})
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

    def _max_depth(self) -> int:
        return self.workflow_config.get("global", {}).get("max_depth", 10)

    def _states_for_kind(self, kind: str) -> list[str]:
        cfg = self.config
        if cfg is None:
            return []
        return cfg.workflow_states(kind)

    def _record(
        self,
        status: str,
        target_id: str,
        target_state: str,
        source_id: str,
        source_state: str,
        metadata: dict[str, Any],
        *,
        target_kind: str | None = None,
        old_state: str | None = None,
        reason: str | None = None,
    ) -> None:
        source_view = self.ctx.lookup(source_id)
        source_kind = None
        if source_view:
            source_kind = getattr(source_view, "kind", None)
            if source_kind is None and source_view.data:
                source_kind = source_view.data.get("kind")
        self._log.append(
            status=status,
            target_id=target_id,
            target_state=target_state,
            source_id=source_id,
            source_kind=source_kind,
            source_state=source_state,
            metadata=metadata,
            target_kind=target_kind,
            old_state=old_state,
            reason=reason,
        )
