"""Config-driven state propagation engine.

The engine is a passive utility: it never subscribes to events directly. Hosts
call :meth:`propagate` after a state change to obtain a list of suggested
follow-up transitions, then call :meth:`apply_propagation` to apply them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error_factory

from .healing_validator import HealingValidator
from .log_recorder import LogRecorder
from .propagation_config import load_config, validate
from .rule_evaluator import PropagationRuleEvaluator
from .workflow_item_api import WorkflowItemAPI

logger = logging.getLogger(__name__)

_propagation_error: Any = make_error_factory("VAL", "WFPROP", "workflow")


class StatePropagationEngine:
    def __init__(
        self,
        ctx: WorkflowItemAPI,
        enabled: bool = True,
        config_path: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        if enabled and config_path is None:
            raise _propagation_error(
                1,
                "StatePropagationEngine enabled=True requires config_path. "
                "Either pass config_path or set enabled=False.",
            )
        self.ctx: Any = ctx
        self._enabled = enabled
        self._config_path = config_path
        self._workflow_config: dict[str, Any] | None = None
        self._log_recorder = LogRecorder(ctx, log_path)
        self._rule_evaluator: PropagationRuleEvaluator | None = None
        self._healing_validator = HealingValidator(self)

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
        self._rule_evaluator = PropagationRuleEvaluator(
            self.ctx, config, config.get("global", {}).get("max_depth", 10)
        )
        return config

    def propagate(
        self,
        item_id: str,
        new_state: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[tuple[str, str, str]]:
        if not self._enabled:
            return []
        if self._rule_evaluator is None:
            self.load_workflow_config()
        return self._rule_evaluator.evaluate(item_id, new_state, metadata)

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
            self._log_recorder.record(
                "failed", target_id, target_state, source_id, source_state, metadata,
                reason="target_not_found",
            )
            return

        target_kind = getattr(target_view, "kind", None) or target_view.data.get("kind")
        cfg = self.config
        if cfg is None:
            raise _propagation_error(2, "State propagation requires Config")

        current_state = target_view.data.get("state", cfg.initial_state(target_kind))

        if current_state == target_state:
            self._log_recorder.record(
                "skipped", target_id, target_state, source_id, source_state, metadata,
                target_kind=target_kind, old_state=current_state,
                reason="already_in_target_state",
            )
            return

        workflow_name = target_view.data.get("workflow")
        current_priority = cfg.state_priority(target_kind, current_state, workflow_name)
        target_priority = cfg.state_priority(target_kind, target_state, workflow_name)
        if target_priority < current_priority:
            self._log_recorder.record(
                "skipped", target_id, target_state, source_id, source_state, metadata,
                target_kind=target_kind, old_state=current_state,
                reason="lower_priority_than_current_state",
            )
            return

        current_depth = metadata.get("propagation_depth", 0)
        if current_depth >= self._max_depth():
            self._log_recorder.record(
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
        except (AudiaGenticError, ValueError) as exc:
            self._log_recorder.record(
                "skipped", target_id, target_state, source_id, source_state, new_metadata,
                target_kind=target_kind, old_state=current_state, reason="invalid_transition",
            )
            logger.debug("Propagation skipped invalid transition for %s: %s", target_id, exc)
            return
        except Exception as exc:
            self._log_recorder.record(
                "failed", target_id, target_state, source_id, source_state, new_metadata,
                target_kind=target_kind, old_state=current_state, reason=str(exc),
            )
            raise

        self._log_recorder.record(
            "success", target_id, target_state, source_id, source_state, new_metadata,
            target_kind=target_kind, old_state=current_state,
        )
        logger.info(
            "Propagated state: %s -> %s triggered by %s (%s)",
            target_id, target_state, source_id, source_state,
        )

    # ---- healing facade ------------------------------------------------

    def validate_hierarchy(self, item_id: str) -> list[dict[str, Any]]:
        return self._healing_validator.validate_hierarchy(item_id)

    def heal_hierarchy(self, item_id: str, auto_fix: bool = False) -> dict[str, Any]:
        return self._healing_validator.heal_hierarchy(item_id, auto_fix)

    def apply_healing_fix(self, fix: dict[str, Any]) -> None:
        self._healing_validator.apply_healing_fix(fix)

    # ---- internals -----------------------------------------------------

    def _max_depth(self) -> int:
        return self.workflow_config.get("global", {}).get("max_depth", 10)

    def _states_for_kind(self, kind: str) -> list[str]:
        cfg = self.config
        if cfg is None:
            return []
        return cfg.workflow_states(kind)
