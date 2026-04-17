"""State propagation engine for planning hierarchies.

Config-driven state propagation across planning items. The engine is completely
agnostic about workflows and document relationships - all rules, actions, and
relationships are defined in the config file.

This is a passive utility - it does NOT subscribe to events. The owner component
(planning) is responsible for registering event handlers and calling propagate().

Architecture:
- Rules are defined in config and implemented as separate functions in propagation_rules.py
- Actions are defined in config and implemented as separate functions in propagation_rules.py
- The engine only orchestrates - it doesn't contain any business logic
- New workflows can be added by creating new config files without modifying code
"""

from __future__ import annotations

import importlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .propagation_interface import PlanningAPIInterface

logger = logging.getLogger(__name__)


class StatePropagationEngine:
    """Config-driven state propagation engine.

    This is a PASSIVE UTILITY that calculates state propagations. It does NOT
    subscribe to events or apply changes automatically. The owner component
    (planning) must:
    1. Register its own event handlers
    2. Call propagate() to get propagation suggestions
    3. Call apply_propagation() to apply each suggestion

    Usage:
        # In planning component __init__:
        self._propagation_engine = StatePropagationEngine(
            planning_api=self,
            config_path=self.root / ".audiagentic" / "planning" / "config" / "state_propagation.yaml",
        )

        # Register event handler:
        self._bus.subscribe("planning.item.state.changed", self._on_state_change)

        # In _on_state_change handler:
        propagations = self._propagation_engine.propagate(item_id, new_state)
        for target_id, target_kind, target_state in propagations:
            self._propagation_engine.apply_propagation(
                target_id=target_id,
                target_state=target_state,
                source_id=item_id,
                source_state=new_state,
                metadata=metadata,
            )
    """

    def __init__(
        self,
        planning_api: PlanningAPIInterface,
        enabled: bool = True,
        config_path: Path | None = None,
    ) -> None:
        """Initialize the state propagation engine.

        Args:
            planning_api: PlanningAPI instance for item lookup
            enabled: Whether propagation is enabled globally
            config_path: Optional path to config file (passed by owner component)

        Raises:
            ValueError: If enabled=True but config_path is None
        """
        self._planning_api: PlanningAPIInterface = planning_api
        self._enabled = enabled
        self._config: dict[str, Any] | None = None
        self._config_path: Path | None = config_path

        if enabled and config_path is None:
            raise ValueError(
                "StatePropagationEngine enabled=True requires config_path. "
                "Either pass config_path or set enabled=False."
            )

    def _ensure_config_loaded(self) -> None:
        """Ensure config is loaded, loading if necessary."""
        if self._config is None:
            self.load_workflow_config()

    def _get_item_with_kind(self, item_id: str) -> tuple[Any, str | None]:
        """Get item view and kind, or (None, None) if not found.

        Args:
            item_id: Item ID to lookup

        Returns:
            Tuple of (item_view, kind) or (None, None) if not found
        """
        item_view = self._planning_api.lookup(item_id)
        if not item_view or not item_view.data:
            return (None, None)

        kind = getattr(item_view, "kind", None) or item_view.data.get("kind")
        return (item_view, kind)

    def _get_kind_config(self, kind: str) -> dict[str, Any]:
        """Get configuration for a kind.

        Args:
            kind: Item kind

        Returns:
            Kind config dict, or empty dict if not configured
        """
        return self._config.get("kinds", {}).get(kind, {}) if self._config else {}

    def _get_parents(self, item_id: str, kind: str) -> list[tuple[str, str]]:
        """Get parent items for an item.

        Args:
            item_id: Item ID
            kind: Item kind

        Returns:
            List of (parent_id, parent_kind) tuples
        """
        kind_config = self._get_kind_config(kind)
        return self._find_parents(item_id, kind_config)

    def propagate(
        self, item_id: str, new_state: str, metadata: dict[str, Any] | None = None
    ) -> list[tuple[str, str, str]]:
        """Calculate state propagations for a state change.

        This method calculates what propagations should happen but does NOT
        apply them. The caller must call apply_propagation() for each result.

        Args:
            item_id: Item ID that changed state
            new_state: New state of the item
            metadata: Optional event metadata (used to check propagation_depth and healing_fix)

        Returns:
            List of (target_id, target_kind, target_state) tuples for propagation
        """
        if not self._enabled:
            return []

        if metadata and metadata.get("healing_fix"):
            return []

        max_depth = self._get_max_depth()
        current_depth = (metadata or {}).get("propagation_depth", 0)
        if current_depth >= max_depth:
            logger.warning(
                "propagate() max depth %d reached (current: %d)", max_depth, current_depth
            )
            return []

        item_view, kind = self._get_item_with_kind(item_id)
        if not item_view or not kind:
            return []

        self._ensure_config_loaded()

        global_config = self._config.get("global", {})
        if not global_config.get("enabled", True):
            return []

        kind_config = self._get_kind_config(kind)
        if not kind_config.get("enabled", True):
            return []

        propagation_override = item_view.data.get("propagation", {})
        if propagation_override and propagation_override.get("enabled") is False:
            return []

        state_rules = kind_config.get("state_rules", {}).get(new_state, {})
        rule = state_rules.get("rule", "none")
        target_state = state_rules.get("new_state")

        if not target_state or rule == "none":
            return []

        parents = self._get_parents(item_id, kind)
        if not parents:
            return []

        propagations = []
        for parent_id, parent_kind in parents:
            if self._apply_rule(item_id, parent_id, new_state, rule):
                propagations.append((parent_id, parent_kind, target_state))

                actions = state_rules.get("actions", [])
                for action_name in actions:
                    action_propagations = self._execute_action(action_name, parent_id, state_rules)
                    propagations.extend(action_propagations)

        return propagations

    def apply_propagation(
        self,
        target_id: str,
        target_state: str,
        source_id: str,
        source_state: str,
        metadata: dict[str, Any],
    ) -> None:
        """Apply a state propagation to a target item.

        This method is called by the planning component after it receives
        propagation suggestions from propagate().

        Args:
            target_id: Target item ID to update
            target_state: New state to set
            source_id: Source item ID that triggered propagation
            source_state: Source item state that triggered propagation
            metadata: Event metadata to propagate
        """
        # Check if target exists
        target_view = self._planning_api.lookup(target_id)
        if not target_view or not target_view.data:
            logger.warning("Target item not found: %s", target_id)
            self._log_propagation_attempt(
                status="failed",
                target_id=target_id,
                target_state=target_state,
                source_id=source_id,
                source_state=source_state,
                metadata=metadata,
                reason="target_not_found",
            )
            return

        current_state = target_view.data.get("state", "ready")
        target_kind = getattr(target_view, "kind", None) or target_view.data.get("kind")

        # Skip if already in target state
        if current_state == target_state:
            logger.debug(
                "Skipping propagation to %s: already in state %s",
                target_id,
                target_state,
            )
            self._log_propagation_attempt(
                status="skipped",
                target_id=target_id,
                target_state=target_state,
                source_id=source_id,
                source_state=source_state,
                metadata=metadata,
                target_kind=target_kind,
                old_state=current_state,
                reason="already_in_target_state",
            )
            return

        if not self._is_valid_transition(target_view, target_state):
            logger.info(
                "Skipping propagation to %s: invalid workflow transition %s -> %s",
                target_id,
                current_state,
                target_state,
            )
            self._log_propagation_attempt(
                status="skipped",
                target_id=target_id,
                target_state=target_state,
                source_id=source_id,
                source_state=source_state,
                metadata=metadata,
                target_kind=target_kind,
                old_state=current_state,
                reason="invalid_transition",
            )
            return

        # Check state priority to avoid downgrading
        if self._config is None:
            self.load_workflow_config()

        state_priority = self._config.get("state_priority", {})
        if state_priority:
            current_priority = state_priority.get(current_state, 0)
            target_priority = state_priority.get(target_state, 0)

            if target_priority < current_priority:
                logger.debug(
                    "Skipping propagation to %s: %s (priority %d) < %s (priority %d)",
                    target_id,
                    target_state,
                    target_priority,
                    current_state,
                    current_priority,
                )
                self._log_propagation_attempt(
                    status="skipped",
                    target_id=target_id,
                    target_state=target_state,
                    source_id=source_id,
                    source_state=source_state,
                    metadata=metadata,
                    target_kind=target_kind,
                    old_state=current_state,
                    reason="lower_priority_than_current_state",
                )
                return

        # Check max depth before applying
        max_depth = self._get_max_depth()
        current_depth = metadata.get("propagation_depth", 0)
        if current_depth >= max_depth:
            logger.warning(
                "apply_propagation() skipping: max depth %d reached (current: %d) for %s",
                max_depth,
                current_depth,
                target_id,
            )
            self._log_propagation_attempt(
                status="skipped",
                target_id=target_id,
                target_state=target_state,
                source_id=source_id,
                source_state=source_state,
                metadata=metadata,
                target_kind=target_kind,
                old_state=current_state,
                reason="max_depth_reached",
            )
            return

        # Update state via planning API
        # Increment propagation depth in metadata
        new_metadata = metadata.copy()
        new_metadata["propagation_depth"] = current_depth + 1
        new_metadata["propagation_source"] = source_id
        new_metadata["propagation_trigger"] = f"{source_id}:{source_state}"

        # Use planning API to update state (which will publish the event)
        try:
            self._planning_api.state(
                id_=target_id,
                new_state=target_state,
                metadata=new_metadata,
            )
        except Exception as e:
            self._log_propagation_attempt(
                status="failed",
                target_id=target_id,
                target_state=target_state,
                source_id=source_id,
                source_state=source_state,
                metadata=new_metadata,
                target_kind=target_kind,
                old_state=current_state,
                reason=str(e),
            )
            raise

        self._log_propagation_attempt(
            status="success",
            target_id=target_id,
            target_state=target_state,
            source_id=source_id,
            source_state=source_state,
            metadata=new_metadata,
            target_kind=target_kind,
            old_state=current_state,
        )

        logger.info(
            "Propagated state: %s -> %s triggered by %s (%s)",
            target_id,
            target_state,
            source_id,
            source_state,
        )

    def _is_valid_transition(self, target_view: Any, target_state: str) -> bool:
        """Check whether the target item can legally enter the propagated state."""
        config = getattr(self._planning_api, "config", None)
        if config is None:
            return True

        target_kind = getattr(target_view, "kind", None) or target_view.data.get("kind")
        if not target_kind:
            return True

        workflow_name = target_view.data.get("workflow")
        workflow = config.workflow_for(target_kind, workflow_name)
        current_state = target_view.data.get("state", "ready")

        if target_state not in workflow.get("values", []):
            return False

        return target_state in workflow.get("transitions", {}).get(current_state, [])

    def _propagation_log_path(self) -> Path | None:
        root = getattr(self._planning_api, "root", None)
        if root is None:
            return None
        return Path(root) / ".audiagentic" / "planning" / "meta" / "propagation_log.json"

    def _log_propagation_attempt(
        self,
        *,
        status: str,
        target_id: str,
        target_state: str,
        source_id: str,
        source_state: str,
        metadata: dict[str, Any],
        target_kind: str | None = None,
        old_state: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Append a propagation attempt record for audit/recovery."""
        log_path = self._propagation_log_path()
        if log_path is None:
            return

        source_view = self._planning_api.lookup(source_id)
        source_kind = getattr(source_view, "kind", None) if source_view else None
        if source_kind is None and source_view and source_view.data:
            source_kind = source_view.data.get("kind")

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": metadata.get("correlation_id") or metadata.get("event_id"),
            "correlation_id": metadata.get("correlation_id"),
            "source_kind": source_kind,
            "source_id": source_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "old_state": old_state,
            "new_state": target_state,
            "trigger_source_state": source_state,
            "triggered_by": metadata.get("triggered_by", "automatic"),
            "propagation_depth": metadata.get("propagation_depth", 0),
            "status": status,
        }
        if reason:
            entry["reason"] = reason

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            if log_path.exists():
                data = json.loads(log_path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            else:
                data = []
            data.append(entry)
            log_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to write propagation log entry for %s: %s", target_id, exc)

    def load_workflow_config(self) -> dict[str, Any]:
        """Load propagation configuration.

        Returns:
            Configuration dict. Returns disabled config if file missing or error.

        Note:
            No hardcoded defaults. If config is missing, propagation is disabled.
            This ensures all behavior is explicitly configured and auditable.

            Always assigns to self._config to prevent repeated load attempts on error.
        """
        # Always assign to self._config to prevent repeated load attempts
        config_path = self._find_config_path()
        if not config_path or not config_path.exists():
            logger.warning(
                "Propagation config not found at %s. Propagation disabled.",
                config_path,
            )
            self._config = {"global": {"enabled": False}}
            return self._config

        try:
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}

            # Validate config
            validation_errors = self._validate_config(config)
            if validation_errors:
                logger.warning("Config validation warnings: %s", ", ".join(validation_errors))

            # Load rule implementations
            self._load_rule_implementations(config)

            self._config = config
            self._config_path = config_path
            return config
        except Exception as e:
            logger.error("Failed to load propagation config: %s. Propagation disabled.", e)
            self._config = {"global": {"enabled": False}}
            return self._config

    def _get_max_depth(self) -> int:
        """Get maximum propagation depth from config.

        Returns:
            Maximum depth for propagation chains. Defaults to 10 if not configured.
        """
        if self._config is None:
            return 10

        return self._config.get("global", {}).get("max_depth", 10)

    def _load_rule_implementations(self, config: dict[str, Any]) -> None:
        """Load rule and action implementations from config references.

        Args:
            config: Configuration dict with rule/action references
        """
        # Load rule implementations
        rules = config.get("rules", {})
        for rule_name, rule_config in rules.items():
            logic_ref = rule_config.get("logic")
            if logic_ref and callable(rule_config.get("logic")):
                # Already a callable, use as-is
                continue

            if logic_ref and isinstance(logic_ref, str):
                # Import from module reference (e.g., "propagation_rules.rule_none")
                try:
                    func = self._import_callable(logic_ref)
                    rules[rule_name]["logic"] = func
                except (ImportError, AttributeError) as e:
                    logger.warning("Failed to load rule %s: %s", rule_name, e)
                    rules[rule_name]["logic"] = lambda *args: False

        # Load action implementations
        actions = config.get("actions", {})
        for action_name, action_config in actions.items():
            logic_ref = action_config.get("logic")
            if logic_ref and callable(action_config.get("logic")):
                # Already a callable, use as-is
                continue

            if logic_ref and isinstance(logic_ref, str):
                # Import from module reference
                try:
                    func = self._import_callable(logic_ref)
                    actions[action_name]["logic"] = func
                except (ImportError, AttributeError) as e:
                    logger.warning("Failed to load action %s: %s", action_name, e)
                    actions[action_name]["logic"] = lambda *args: []

    def _import_callable(self, ref: str) -> callable:
        """Import a callable from a module reference.

        Args:
            ref: Module reference (e.g., "audiagentic.interoperability.propagation_rules.rule_none")

        Returns:
            Imported callable
        """
        parts = ref.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid callable reference: {ref}")

        module_name, func_name = parts

        # Try importing as absolute module first
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            # Fall back to relative import
            module = importlib.import_module(module_name, package=__name__)

        func = getattr(module, func_name)

        if not callable(func):
            raise AttributeError(f"{ref} is not callable")

        return func

    def _find_parents(self, item_id: str, config: dict[str, Any]) -> list[tuple[str, str]]:
        """Find parent items based on configuration.

        Args:
            item_id: Item ID to find parents for
            config: Configuration dict with parent_kind and parent_field

        Returns:
            List of (parent_id, parent_kind) tuples
        """
        item_view = self._planning_api.lookup(item_id)
        if not item_view or not item_view.data:
            return []

        parent_kind = config.get("parent_kind")
        parent_field = config.get("parent_field")

        if not parent_kind or not parent_field:
            return []

        parents = []

        # Check if item references parent directly (e.g., plan_ref)
        parent_id = item_view.data.get(parent_field)
        if parent_id:
            # Handle both string and list references
            if isinstance(parent_id, list):
                for pid in parent_id:
                    parents.append((pid, parent_kind))
            else:
                parents.append((parent_id, parent_kind))

        # Check if parent references item (e.g., task_refs in WP)
        # This requires scanning for items with the reverse relationship
        if not parents:
            parents = self._find_reverse_parents(item_id, parent_kind, parent_field)

        return parents

    def _find_reverse_parents(
        self, item_id: str, parent_kind: str, parent_field: str
    ) -> list[tuple[str, str]]:
        """Find parents that reference this item.

        Args:
            item_id: Item ID to find parents for
            parent_kind: Kind of parent item
            parent_field: Field in parent that references children

        Returns:
            List of (parent_id, parent_kind) tuples

        Performance Note:
            This method performs a full table scan via _scan() which is O(n) where
            n is the total number of planning items. This is called when an item
            does not have a direct parent reference (e.g., task without plan_ref).
            For large repositories, consider:
            1. Ensuring items have direct parent references (plan_ref, wp_ref, etc.)
            2. Adding an indexed reverse-ref lookup in PlanningAPI
            3. Caching reverse parent lookups
        """
        # Scan for items of parent_kind (O(n) - see docstring for performance notes)
        all_items = self._planning_api._scan()
        parents = []

        for item_view in all_items:
            # Item.kind is the kind attribute, not in data
            if getattr(item_view, "kind", None) != parent_kind:
                continue

            # Check if this item references our item
            child_refs = item_view.data.get(parent_field, [])
            if isinstance(child_refs, str):
                child_refs = [child_refs]

            # Handle both direct IDs and dict refs with 'ref' key
            for ref in child_refs:
                ref_id = ref.get("ref") if isinstance(ref, dict) else ref
                if ref_id == item_id:
                    parents.append((item_view.data["id"], parent_kind))
                    break

        return parents

    def _apply_rule(
        self,
        child_id: str,
        parent_id: str,
        new_state: str,
        rule: str,
    ) -> bool:
        """Apply a propagation rule to determine if state should propagate.

        Args:
            child_id: Child item ID
            parent_id: Parent item ID
            new_state: New state of child
            rule: Rule name from config

        Returns:
            True if state should propagate to parent
        """
        # Look up rule implementation from config
        rule_configs = self._config.get("rules", {})
        rule_config = rule_configs.get(rule, {})

        # Check if rule is enabled
        if not rule_config.get("enabled", True):
            logger.debug("Rule %s is disabled", rule)
            return False

        # Get rule logic implementation
        logic_func = rule_config.get("logic")
        if not logic_func:
            logger.warning("Rule %s has no logic implementation", rule)
            return False

        # Execute rule logic
        try:
            return logic_func(self, child_id, parent_id, new_state)
        except Exception as e:
            logger.error("Rule %s failed: %s", rule, e)
            return False

    def _execute_action(
        self, action_name: str, item_id: str, state_rules: dict[str, Any]
    ) -> list[tuple[str, str, str]]:
        """Execute a configured action.

        Args:
            action_name: Action name from config
            item_id: Item ID that triggered the action
            state_rules: State rules config for context

        Returns:
            List of (item_id, kind, new_state) tuples for propagation
        """
        # Look up action implementation from config
        action_configs = self._config.get("actions", {})
        action_config = action_configs.get(action_name, {})

        if not action_config.get("enabled", True):
            return []

        # Get action logic implementation
        logic_func = action_config.get("logic")
        if not logic_func:
            logger.warning("Action %s has no logic implementation", action_name)
            return []

        # Execute action logic
        try:
            return logic_func(self, item_id, state_rules)
        except Exception as e:
            logger.error("Action %s failed: %s", action_name, e)
            return []

    def _find_config_path(self) -> Path | None:
        """Find the propagation config file path.

        Returns:
            Path to config file or None if not found
        """
        # Use config_path passed by owner component (preferred)
        if self._config_path:
            if self._config_path.exists():
                return self._config_path
            logger.debug("Config path provided but does not exist: %s", self._config_path)

        return None

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dicts.

        Args:
            base: Base dict
            override: Override dict

        Returns:
            Merged dict

        Note:
            Uses shallow copy for base. For nested dicts, performs deep merge.
            For non-dict values (lists, scalars), override replaces entirely
            (last-write-wins semantics).
        """
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def _validate_config(self, config: dict[str, Any]) -> list[str]:
        """Validate configuration against validation rules.

        Args:
            config: Configuration dict to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Get validation rules from config or use defaults
        validation_rules = config.get("validation", {})

        # Check required fields
        required_fields = validation_rules.get("required_fields", [])
        for field_path in required_fields:
            parts = field_path.split(".")
            value = config
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    errors.append(f"Missing required field: {field_path}")
                    break

        # Check required rules
        required_rules = validation_rules.get("required_rules", [])
        rules = config.get("rules", {})
        for rule_name in required_rules:
            if rule_name not in rules:
                errors.append(f"Missing required rule: {rule_name}")

        # Check valid states in state_rules
        valid_states = validation_rules.get(
            "valid_states", ["ready", "in_progress", "done", "blocked", "archived"]
        )
        kinds = config.get("kinds", {})
        for kind_name, kind_config in kinds.items():
            state_rules = kind_config.get("state_rules", {})
            for state in state_rules.keys():
                if state not in valid_states:
                    errors.append(f"Invalid state '{state}' in kind '{kind_name}'")

        # Check valid rules in state_rules
        valid_rules = validation_rules.get(
            "valid_rules",
            [
                "none",
                "trigger_parent_if_ready",
                "check_all_children_done",
                "trigger_parent_unless_terminal",
            ],
        )
        for kind_name, kind_config in kinds.items():
            state_rules = kind_config.get("state_rules", {})
            for state, state_config in state_rules.items():
                rule = state_config.get("rule")
                if rule and rule not in valid_rules:
                    errors.append(
                        f"Invalid rule '{rule}' for state '{state}' in kind '{kind_name}'"
                    )

        return errors

    def validate_hierarchy(self, item_id: str) -> list[dict[str, Any]]:
        """Validate state consistency for an item and its hierarchy.

        Args:
            item_id: Item ID to validate

        Returns:
            List of validation errors with details
        """
        errors = []

        item_view, kind = self._get_item_with_kind(item_id)
        if not item_view:
            return [{"error": "Item not found", "item_id": item_id}]
        if not kind:
            return [{"error": "Item has no kind", "item_id": item_id}]

        self._ensure_config_loaded()

        kind_config = self._get_kind_config(kind)
        if not kind_config.get("enabled", True):
            return errors

        parent_field = kind_config.get("parent_field")
        if not kind_config.get("parent_kind") or not parent_field:
            return errors

        parents = self._get_parents(item_id, kind)

        for parent_id, found_parent_kind in parents:
            parent_view = self._planning_api.lookup(parent_id)
            if not parent_view or not parent_view.data:
                errors.append(
                    {
                        "error": "Parent not found",
                        "item_id": item_id,
                        "parent_id": parent_id,
                        "parent_kind": found_parent_kind,
                    }
                )
                continue

            item_state = item_view.data.get("state", "draft")
            parent_state = parent_view.data.get("state", "draft")

            if parent_state == "done":
                child_refs = parent_view.data.get(parent_field, [])
                if isinstance(child_refs, str):
                    child_refs = [child_refs]

                for ref in child_refs:
                    ref_id = ref.get("ref") if isinstance(ref, dict) else ref
                    child_view = self._planning_api.lookup(ref_id)
                    if child_view and child_view.data:
                        child_state = child_view.data.get("state", "draft")
                        if child_state not in ["done", "archived"]:
                            errors.append(
                                {
                                    "error": "Parent is done but child is not",
                                    "parent_id": parent_id,
                                    "parent_state": parent_state,
                                    "child_id": ref_id,
                                    "child_state": child_state,
                                }
                            )

            elif parent_state == "draft" and item_state in ["in_progress", "done"]:
                errors.append(
                    {
                        "error": "Child is active but parent is in draft",
                        "parent_id": parent_id,
                        "parent_state": parent_state,
                        "child_id": item_id,
                        "child_state": item_state,
                    }
                )

        return errors

    def heal_hierarchy(self, item_id: str, auto_fix: bool = False) -> dict[str, Any]:
        """Attempt to heal state inconsistencies in the hierarchy.

        Args:
            item_id: Item ID to heal
            auto_fix: If True, automatically apply fixes. If False, only return suggested fixes.

        Returns:
            Dict with 'errors' (list of issues found) and 'fixes' (list of applied/suggested fixes)
        """
        result = {"errors": [], "fixes": []}

        errors = self.validate_hierarchy(item_id)
        result["errors"] = errors

        if not errors:
            return result

        self._ensure_config_loaded()

        healing_config = self._config.get("healing", {})
        auto_fix = auto_fix or healing_config.get("auto_fix", False)
        log_only = healing_config.get("log_only", not auto_fix)

        for error in errors:
            fix = self._suggest_fix(error)
            result["fixes"].append(fix)

            if auto_fix and not log_only and fix.get("can_auto_fix"):
                try:
                    self._apply_fix(fix)
                    fix["applied"] = True
                    logger.info(
                        "Applied healing fix: %s -> %s",
                        fix.get("target_id"),
                        fix.get("target_state"),
                    )
                except Exception as e:
                    logger.error("Failed to apply healing fix: %s", e, exc_info=True)
                    fix["applied"] = False
                    fix["error"] = str(e)
            else:
                logger.warning(
                    "Healing fix not applied (auto_fix=%s, log_only=%s): %s",
                    auto_fix,
                    log_only,
                    fix,
                )

        return result

    def _suggest_fix(self, error: dict[str, Any]) -> dict[str, Any]:
        """Suggest a fix for a validation error.

        Args:
            error: Validation error dict

        Returns:
            Fix suggestion dict
        """
        error_type = error.get("error", "")

        if error_type == "Parent is done but child is not":
            # Suggest marking child as done or parent as not done
            return {
                "error": error,
                "suggestion": "Mark child as done or change parent state",
                "target_id": error.get("child_id"),
                "target_state": "done",
                "can_auto_fix": False,  # Don't auto-fix this - could lose work
            }

        elif error_type == "Child is active but parent is in draft":
            # Suggest moving parent to ready
            return {
                "error": error,
                "suggestion": "Move parent to ready state",
                "target_id": error.get("parent_id"),
                "target_state": "ready",
                "can_auto_fix": True,  # Safe to auto-fix
            }

        return {
            "error": error,
            "suggestion": "Manual review required",
            "can_auto_fix": False,
        }

    def _apply_fix(self, fix: dict[str, Any]) -> None:
        """Apply a healing fix.

        Args:
            fix: Fix dict with target_id and target_state
        """
        target_id = fix.get("target_id")
        target_state = fix.get("target_state")

        if not target_id or not target_state:
            raise ValueError("Fix must have target_id and target_state")

        # Apply with healing metadata to prevent loops
        metadata = {"triggered_by": "healing", "healing_fix": True}
        self._planning_api.state(id_=target_id, new_state=target_state, metadata=metadata)
