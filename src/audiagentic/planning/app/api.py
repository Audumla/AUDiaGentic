from __future__ import annotations

import json
import shutil
import warnings
from datetime import datetime, timezone
from pathlib import Path

from ..fs.read import parse_markdown
from ..fs.scan import scan_items
from ..fs.write import dump_markdown
from .api_types import ItemView
from .claims import Claims
from .config import Config
from .events import EventLog
from .ext_mgr import Extracts
from .id_gen import next_id
from .idx_mgr import Indexer
from .paths import Paths
from .rec_mgr import Reconcile
from .rel_mgr import Relationships
from .val_mgr import Validator

# Optional EventBus integration (task-0281)
try:
    from audiagentic.interoperability import DeliveryMode, get_bus
    from audiagentic.planning.app.propagation import StatePropagationEngine

    _EVENT_BUS_ENABLED = True
except ImportError:
    _EVENT_BUS_ENABLED = False
    _EVENT_BUS = None
    StatePropagationEngine = None  # type: ignore


class PlanningAPI:
    def __init__(self, root: Path, test_mode: bool = False):
        self.root = Path(root)
        self.test_mode = test_mode
        self.config = Config(self.root)
        self.paths = Paths(self.root)
        self.events = EventLog(self.root / ".audiagentic/planning/events/events.jsonl")
        self.claims_store = Claims(self.root / ".audiagentic/planning/claims/claims.json")
        self.indexer = Indexer(self.root)
        self.validator = Validator(self.root)
        self.extracts = Extracts(self.root, api_getter=lambda: self)
        self.reconciler = Reconcile(self.root)

        # Initialize state propagation engine (task-0279)
        self._propagation_engine = None
        self._propagation_subscription = None
        if _EVENT_BUS_ENABLED and StatePropagationEngine is not None:
            try:
                # Pass config path from planning component (owner)
                config_path = (
                    self.root / ".audiagentic" / "planning" / "config" / "state_propagation.yaml"
                )
                self._propagation_engine = StatePropagationEngine(
                    planning_api=self,
                    enabled=True,
                    config_path=config_path,
                )
                # Register event handler (planning component owns the subscription)
                bus = get_bus()
                self._propagation_subscription = bus.subscribe(
                    "planning.item.state.changed",
                    self._on_state_change_for_propagation,
                )
            except Exception as e:
                warnings.warn(
                    f"State propagation engine initialization failed: {e}", RuntimeWarning
                )

        # Setup knowledge component event subscriptions (task-0282)
        # Planning component explicitly subscribes knowledge to its events
        if _EVENT_BUS_ENABLED:
            try:
                from audiagentic.knowledge import setup_event_subscriptions

                setup_event_subscriptions()
            except ImportError:
                pass
            except Exception as e:
                warnings.warn(f"Knowledge event subscription setup failed: {e}", RuntimeWarning)

    def _scan(self):
        return scan_items(self.root)

    def _publish_event(
        self,
        event_type: str,
        payload: dict,
        metadata: dict | None = None,
        mode: DeliveryMode = DeliveryMode.ASYNC,
    ) -> None:
        """Publish an event to the event bus and JSONL log.

        Args:
            event_type: Event type string
            payload: Event payload
            metadata: Optional event metadata
            mode: Delivery mode (SYNC or ASYNC)
        """
        # Write to JSONL log for knowledge component scanning
        self.events.emit(event_type, payload)

        # Publish to event bus for in-process subscribers
        if not _EVENT_BUS_ENABLED:
            return

        try:
            bus = get_bus()
            bus.publish(
                event_type=event_type,
                payload=payload,
                metadata=metadata or {},
                mode=mode,
            )
        except Exception as e:
            warnings.warn(f"Event publish failed for {event_type}: {e}", RuntimeWarning)

    def _on_state_change_for_propagation(
        self,
        event_type: str,
        payload: dict,
        metadata: dict,
    ) -> None:
        """Handle state change events for propagation.

        This is the planning component's event handler that triggers propagation.
        The propagation engine is a passive utility - it doesn't subscribe to events.

        Args:
            event_type: Event type (should be "planning.item.state.changed")
            payload: Event payload with id, old_state, new_state
            metadata: Event metadata with correlation_id, propagation_depth
        """
        if not self._propagation_engine:
            return

        item_id = payload.get("id")
        new_state = payload.get("new_state")

        if not item_id or not new_state:
            return

        # Check propagation depth to prevent cycles
        propagation_depth = metadata.get("propagation_depth", 0)
        max_depth = 10  # Default max depth
        if self._propagation_engine._config:
            max_depth = self._propagation_engine._config.get("global", {}).get("max_depth", 10)

        if propagation_depth >= max_depth:
            return

        # Calculate propagations
        propagations = self._propagation_engine.propagate(item_id, new_state)

        if not propagations:
            return

        # Apply propagations
        for target_id, target_kind, target_state in propagations:
            self._propagation_engine.apply_propagation(
                target_id=target_id,
                target_state=target_state,
                source_id=item_id,
                source_state=new_state,
                metadata=metadata,
            )

    def _lookup_index_path(self) -> Path:
        return self.root / ".audiagentic/planning/indexes/lookup.json"

    def _load_lookup_index(self) -> dict[str, dict]:
        path = self._lookup_index_path()
        if not path.exists():
            raise FileNotFoundError(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("items", {})

    def _item_to_head(self, item: ItemView) -> dict[str, object]:
        return {
            "id": item.data["id"],
            "kind": item.kind,
            "label": item.data["label"],
            "state": item.data["state"],
            "path": item.path.relative_to(self.root).as_posix(),
            "deleted": bool(item.data.get("deleted", False)),
        }

    def _assert_not_archived(self, item: ItemView, action: str) -> None:
        if item.data.get("state") == "archived":
            raise ValueError(f"cannot {action} archived item {item.data['id']}; restore it first")

    def _normalize_id(self, id_: str) -> str:
        """Normalize ID format (e.g., request-41 → request-041)."""
        parts = id_.split("-", 1)
        if len(parts) != 2:
            return id_

        kind, num_part = parts
        try:
            num = int(num_part)
            # Determine padding based on kind
            if kind == "task":
                return f"{kind}-000{num}"
            elif kind in ("standard",):
                # Check if has suffix like standard-0010-python
                if "-" in num_part:
                    return id_  # Keep as-is
                return f"{kind}-00{num}"
            else:
                # request, spec, plan, wp use 3-digit padding
                return f"{kind}-{num:03d}"
        except ValueError:
            return id_

    def _find_similar_ids(self, id_: str) -> list[str]:
        """Find IDs similar to the requested one, sorted by numeric proximity."""
        parts = id_.split("-", 1)
        if len(parts) != 2:
            return []

        kind, num_part = parts
        target_num = None
        try:
            target_num = int(num_part.split("-")[0])
        except ValueError:
            pass

        similar = []
        for item in self._scan():
            if item.kind == kind and not item.data.get("deleted", False):
                similar.append(item.data["id"])

        # Sort by numeric proximity to target
        def extract_num(id_str):
            try:
                return int(id_str.split("-")[1].split("-")[0])
            except (IndexError, ValueError):
                return 0

        if target_num is not None:
            similar.sort(key=lambda x: (abs(extract_num(x) - target_num), extract_num(x)))
        else:
            similar.sort(key=extract_num)
        return similar[:10]

    def _fallback_scan_item(self, id_: str) -> ItemView:
        # Try exact match first
        for item in self._scan():
            if item.data["id"] == id_:
                return item

        # Try normalized ID
        normalized = self._normalize_id(id_)
        if normalized != id_:
            for item in self._scan():
                if item.data["id"] == normalized:
                    return item

        # Not found - provide helpful error
        similar = self._find_similar_ids(id_)
        if similar:
            msg = f"{id_} not found (tried {normalized if normalized != id_ else 'exact match'}). "
            msg += f"Closest: {similar[0]}. "
            msg += f"Available {len(similar)} items: {', '.join(similar[:5])}"
            if len(similar) > 5:
                msg += f" and {len(similar) - 5} more"
            msg += ". Use tm_list kind=request to see all"
            raise ValueError(msg)
        else:
            raise ValueError(
                f"{id_} not found (no items of this kind). Use tm_list to discover available items"
            )

    def lookup(self, id_: str) -> ItemView:
        # Try exact match first
        try:
            entry = self._load_lookup_index().get(id_)
        except FileNotFoundError:
            warnings.warn(
                "lookup.json is missing; falling back to scan_items()",
                RuntimeWarning,
                stacklevel=2,
            )
            return self._fallback_scan_item(id_)

        if entry:
            path = self.root / Path(entry["path"])
            if path.exists():
                data, body = parse_markdown(path)
                return ItemView(entry["kind"], path, data, body)

        # Try normalized ID
        normalized = self._normalize_id(id_)
        if normalized != id_:
            try:
                entry = self._load_lookup_index().get(normalized)
                if entry:
                    path = self.root / Path(entry["path"])
                    if path.exists():
                        data, body = parse_markdown(path)
                        return ItemView(entry["kind"], path, data, body)
            except FileNotFoundError:
                pass

        # Fall back to scan with smart error
        return self._fallback_scan_item(id_)

    def head(self, id_: str) -> dict[str, object]:
        try:
            entry = self._load_lookup_index().get(id_)
        except FileNotFoundError:
            warnings.warn(
                "lookup.json is missing; falling back to scan_items()",
                RuntimeWarning,
                stacklevel=2,
            )
            return self._item_to_head(self._fallback_scan_item(id_))

        if entry:
            return dict(entry)

        return self._item_to_head(self._fallback_scan_item(id_))

    def _find(self, id_: str):
        try:
            return self.lookup(id_)
        except ValueError as exc:
            raise KeyError(id_) from exc

    def _append_unique_ref(self, src_id: str, field: str, dst_id: str) -> None:
        item = self._find(src_id)
        data, body = parse_markdown(item.path)
        vals = list(data.get(field, []) or [])
        if dst_id in vals:
            return
        vals.append(dst_id)
        data[field] = vals
        dump_markdown(item.path, data, body)

    def _sync_request_spec_refs(self, spec_id: str, request_refs: list[str] | None = None) -> None:
        for req_id in request_refs or []:
            request = self._find(req_id)
            if request.kind != "request":
                raise ValueError(f"request '{req_id}' does not exist")
            self._append_unique_ref(req_id, "spec_refs", spec_id)

    def validate(self, raise_on_error: bool = False):
        errors = self.validator.validate_all()
        if raise_on_error and errors:
            raise RuntimeError("\n".join(errors))
        return errors

    def index(self):
        self.indexer.write_indexes()

    def rebaseline(self) -> dict:
        """Completely rebuild all indexes and extracts from source docs.

        Use after bulk ID changes or when indexes become corrupted.
        Clears all cached data and rebuilds from scratch.

        Returns:
            Summary of what was rebuilt
        """
        import shutil

        # Clear indexes
        idx_dir = self.root / ".audiagentic/planning/indexes"
        if idx_dir.exists():
            shutil.rmtree(idx_dir)
            idx_dir.mkdir(parents=True)

        # Clear extracts
        ext_dir = self.root / ".audiagentic/planning/extracts"
        if ext_dir.exists():
            shutil.rmtree(ext_dir)
            ext_dir.mkdir(parents=True)

        # Rebuild indexes
        self.indexer.write_indexes()

        # Rebuild extracts for all items (skip items with broken refs)
        items = self._scan()
        rebuilt = 0
        skipped = []
        for item in items:
            if not item.data.get("deleted"):
                try:
                    self.extracts.extract(
                        item.data["id"],
                        with_related=False,
                        with_resources=False,
                        include_body=True,
                        write_to_disk=True,
                    )
                    rebuilt += 1
                except ValueError as e:
                    skipped.append({"id": item.data["id"], "error": str(e)})

        return {
            "indexes_rebuilt": True,
            "extracts_rebuilt": rebuilt,
            "extracts_skipped": len(skipped),
            "skipped_items": skipped,
            "total_items": len(items),
        }

    def reconcile(self):
        result = self.reconciler.run()
        self.index()

        self._publish_event(
            "planning.reconciled",
            {"orphans": result["orphans"]},
            {"triggered_by": "manual"},
        )

        return result

    def new(
        self,
        kind: str,
        label: str,
        summary: str,
        domain: str | None = None,
        spec: str | None = None,
        plan: str | None = None,
        parent: str | None = None,
        target: str | None = None,
        workflow: str | None = None,
        request_refs: list[str] | None = None,
        standard_refs: list[str] | None = None,
        profile: str | None = None,
        guidance: str | None = None,
        current_understanding: str | None = None,
        open_questions: list[str] | None = None,
        source: str | None = None,
        context: str | None = None,
        check_duplicates: bool = True,
    ) -> ItemView:
        """Create a new planning item - fully config-driven.

        This method now works with any kind defined in planning.yaml.
        Add new kinds by updating the config, not the code.

        Args:
            kind: Planning kind (must be defined in config)
            label: Item label
            summary: Item summary
            domain: Optional domain for kinds that support it
            spec: Optional spec reference
            plan: Optional plan reference
            parent: Optional parent reference
            target: Optional target reference
            workflow: Optional workflow reference
            request_refs: Optional list of request references
            standard_refs: Optional list of standard references
            profile: Optional profile (for requests)
            guidance: Optional guidance level (for requests)
            current_understanding: Optional initial understanding (for requests)
            open_questions: Optional initial questions (for requests)
            source: Optional source identifier (required for requests)
            context: Optional context (for requests)
            check_duplicates: Whether to check for duplicates

        Returns:
            Created ItemView

        Raises:
            ValueError: If kind not in config or required refs missing
        """
        from ..domain.states import KIND_MAP

        # Normalize kind using KIND_MAP
        kind = KIND_MAP.get(kind, kind)

        # Validate kind exists in config
        try:
            kind_config = self.config.kind_config(kind)
        except ValueError:
            available = self.config.all_kinds()
            raise ValueError(
                f"Unknown kind '{kind}'. Add it to planning.yaml or use one of: {available}"
            )

        # Apply default standards if not explicitly provided
        if standard_refs is None and kind in {"spec", "task", "plan", "wp", "request"}:
            standard_refs = self.config.standard_defaults_for(kind)
        else:
            standard_refs = standard_refs or []

        # Validate required refs from config
        required_refs = kind_config.get("required_refs", [])
        self._validate_required_refs(
            kind,
            required_refs,
            {
                "spec": spec,
                "plan": plan,
                "request_refs": request_refs,
            },
        )

        # Kind-specific validations
        if kind in {"request", "spec"} and check_duplicates:
            self._check_duplicate(kind, label, summary)
        if kind in {"spec", "plan", "task"}:
            self._validate_request_refs(request_refs or [])
        if kind == "spec":
            self._require_request_refs_for_spec(request_refs or [])
        if kind == "request" and not source:
            raise ValueError("request requires --source to track request origin")

        # Generate ID using config-defined prefix and counter
        id_ = self._next_id_for_kind(kind)

        # Create item using appropriate manager (backward compatible)
        path = self._create_item_with_manager(
            kind=kind,
            id_=id_,
            label=label,
            summary=summary,
            domain=domain,
            spec=spec,
            plan=plan,
            parent=parent,
            target=target,
            workflow=workflow,
            request_refs=request_refs or [],
            standard_refs=standard_refs,
            profile=profile,
            guidance=guidance,
            current_understanding=current_understanding,
            open_questions=open_questions,
            source=source,
            context=context,
            kind_config=kind_config,
        )

        # Handle request profile cascade
        if kind == "request" and source and source.startswith("refinement-of-"):
            superseded_id = source.replace("refinement-of-", "")
            self._auto_supersede(superseded_id, id_)

        if kind == "request" and profile:
            prof = self.config.profile_for(profile)
            cascade = prof.get("on_request_create", [])
            if "specification" in cascade:
                spec_id = self._next_id_for_kind("spec")
                spec_kind_config = self.config.kind_config("spec")
                self._create_item_with_manager(
                    kind="spec",
                    id_=spec_id,
                    label=f"{label} — Specification",
                    summary=f"Specification for {summary}",
                    domain=None,
                    spec=None,
                    plan=None,
                    parent=None,
                    target=None,
                    workflow=None,
                    request_refs=[id_],
                    standard_refs=[],
                    profile=None,
                    guidance=None,
                    current_understanding=None,
                    open_questions=None,
                    source=None,
                    context=None,
                    kind_config=spec_kind_config,
                )
            elif "task" in cascade:
                task_id = self._next_id_for_kind("task")
                task_kind_config = self.config.kind_config("task")
                self._create_item_with_manager(
                    kind="task",
                    id_=task_id,
                    label=f"{label} — Task",
                    summary=f"Task for {summary}",
                    domain="core",
                    spec=None,
                    plan=None,
                    parent=None,
                    target=None,
                    workflow=None,
                    request_refs=[id_],
                    standard_refs=[],
                    profile=None,
                    guidance=None,
                    current_understanding=None,
                    open_questions=None,
                    source=None,
                    context=None,
                    kind_config=task_kind_config,
                )

        self._publish_event(
            "planning.item.created",
            {"id": id_, "kind": kind, "path": str(path.relative_to(self.root))},
            {"triggered_by": "manual"},
        )

        self.index()
        return self._find(id_)

    def _next_id_for_kind(self, kind: str) -> str:
        """Generate next ID for a kind using config-defined counter file.

        Args:
            kind: Planning kind

        Returns:
            Next ID string (e.g., 'req-001', 'task-0001')
        """
        id_prefix = self.config.kind_id_prefix(kind)
        counter_file = self.config.kind_counter_file(kind)
        counter_path = self.root / ".audiagentic" / "planning" / "meta" / counter_file
        return next_id(counter_path, id_prefix)

    def _validate_required_refs(self, kind: str, required_refs: list[str], provided: dict) -> None:
        """Validate that all required references are provided.

        Args:
            kind: Planning kind
            required_refs: List of required reference field names
            provided: Dict of provided references
        """
        for ref_field in required_refs:
            value = provided.get(ref_field)
            if not value:
                raise ValueError(
                    f"Kind '{kind}' requires '{ref_field}' reference. "
                    f"Add it to planning.yaml kinds.{kind}.required_refs if this is incorrect."
                )

    def _create_item_direct(
        self,
        kind: str,
        id_: str,
        label: str,
        summary: str,
        domain: str | None = None,
        spec: str | None = None,
        plan: str | None = None,
        parent: str | None = None,
        target: str | None = None,
        workflow: str | None = None,
        request_refs: list[str] | None = None,
        standard_refs: list[str] | None = None,
        profile: str | None = None,
        guidance: str | None = None,
        current_understanding: str | None = None,
        open_questions: list[str] | None = None,
        source: str | None = None,
        context: str | None = None,
        state: str | None = None,
        task_refs: list[dict] | None = None,
    ) -> Path:
        """Create a planning item directly without validation or cascading.

        This is a low-level method for internal use when creating items
        as part of cascading operations or overlays.

        Args:
            kind: Planning kind
            id_: Item ID
            label: Item label
            summary: Item summary
            ... (other fields)

        Returns:
            Path to created item
        """
        if guidance is None:
            guidance = self.config.default_guidance()

        frontmatter = {
            "id": id_,
            "label": label,
            "state": state or ("draft" if kind != "request" else "captured"),
            "summary": summary,
        }

        if domain:
            frontmatter["domain"] = domain

        if kind == "request":
            profile_cfg = {}
            if profile:
                try:
                    profile_cfg = self.config.profile_for(profile)
                except ValueError:
                    pass

            defaults = profile_cfg.get("defaults", {})
            default_understanding = defaults.get("current_understanding")
            default_open_questions = defaults.get("open_questions", [])
            default_meta = defaults.get("meta", {})

            guidance_cfg = self.config.guidance_levels().get(guidance, {})
            guidance_defaults = guidance_cfg.get("defaults", {})
            guidance_understanding = guidance_defaults.get("current_understanding")
            guidance_open_questions = guidance_defaults.get("open_questions", [])

            frontmatter["source"] = source or ""
            frontmatter["guidance"] = guidance
            frontmatter["current_understanding"] = (
                current_understanding
                or default_understanding
                or guidance_understanding
                or f"Initial request intake captured: {summary}"
            )
            frontmatter["open_questions"] = (
                open_questions
                if open_questions is not None
                else (default_open_questions or guidance_open_questions or [])
            )
            if context:
                frontmatter["context"] = context
            if default_meta:
                frontmatter["meta"] = default_meta
            if standard_refs:
                frontmatter["standard_refs"] = standard_refs
            if request_refs:
                frontmatter["spec_refs"] = request_refs

        elif kind == "spec":
            frontmatter["request_refs"] = request_refs or []
            frontmatter["task_refs"] = []
            if standard_refs:
                frontmatter["standard_refs"] = standard_refs

        elif kind == "plan":
            frontmatter["spec_refs"] = [spec] if spec else []
            frontmatter["request_refs"] = request_refs or []
            frontmatter["work_package_refs"] = []
            if standard_refs:
                frontmatter["standard_refs"] = standard_refs

        elif kind == "task":
            if spec:
                frontmatter["spec_ref"] = spec
            if parent:
                frontmatter["parent_task_ref"] = parent
            if target:
                frontmatter["target"] = target
            if workflow:
                frontmatter["workflow"] = workflow
            if request_refs:
                frontmatter["request_refs"] = request_refs
            if standard_refs:
                frontmatter["standard_refs"] = standard_refs

        elif kind == "wp":
            if plan:
                frontmatter["plan_ref"] = plan
            frontmatter["task_refs"] = task_refs or []
            if workflow:
                frontmatter["workflow"] = workflow
            if standard_refs:
                frontmatter["standard_refs"] = standard_refs

        body = self.config.document_template(kind, guidance)
        path = self.paths.kind_file(kind, id_, label, domain)
        dump_markdown(path, frontmatter, body)

        if kind == "spec" and request_refs:
            self._sync_request_spec_refs(id_, request_refs)

        return path

    def _build_frontmatter(
        self,
        kind: str,
        id_: str,
        label: str,
        summary: str,
        domain: str | None,
        spec: str | None,
        plan: str | None,
        parent: str | None,
        target: str | None,
        workflow: str | None,
        request_refs: list[str],
        standard_refs: list[str],
        profile: str | None,
        guidance: str | None,
        current_understanding: str | None,
        open_questions: list[str] | None,
        source: str | None,
        context: str | None,
    ) -> dict:
        """Build frontmatter dict for a planning item based on kind.

        This method consolidates all frontmatter building logic into a single
        config-driven approach, eliminating the need for individual manager classes.

        Args:
            kind: Planning kind
            ... (all other fields)

        Returns:
            Frontmatter dict ready for dump_markdown()
        """
        if guidance is None:
            guidance = self.config.default_guidance()

        frontmatter = {
            "id": id_,
            "label": label,
            "state": "draft" if kind != "request" else "captured",
            "summary": summary,
        }

        # Add domain if applicable
        if domain:
            frontmatter["domain"] = domain

        # Kind-specific fields
        if kind == "request":
            # Handle profile defaults
            profile_cfg = {}
            if profile:
                try:
                    profile_cfg = self.config.profile_for(profile)
                except ValueError:
                    pass

            defaults = profile_cfg.get("defaults", {})
            default_understanding = defaults.get("current_understanding")
            default_open_questions = defaults.get("open_questions", [])
            default_meta = defaults.get("meta", {})

            # Handle guidance defaults
            guidance_cfg = self.config.guidance_levels().get(guidance, {})
            guidance_defaults = guidance_cfg.get("defaults", {})
            guidance_understanding = guidance_defaults.get("current_understanding")
            guidance_open_questions = guidance_defaults.get("open_questions", [])

            frontmatter["source"] = source or ""
            frontmatter["guidance"] = guidance
            frontmatter["current_understanding"] = (
                current_understanding
                or default_understanding
                or guidance_understanding
                or f"Initial request intake captured: {summary}"
            )
            frontmatter["open_questions"] = (
                open_questions
                if open_questions is not None
                else (default_open_questions or guidance_open_questions or [])
            )
            if context:
                frontmatter["context"] = context
            if default_meta:
                frontmatter["meta"] = default_meta
            if standard_refs:
                frontmatter["standard_refs"] = standard_refs
            if request_refs:
                frontmatter["spec_refs"] = request_refs

        elif kind == "spec":
            frontmatter["request_refs"] = request_refs or []
            frontmatter["task_refs"] = []
            if standard_refs:
                frontmatter["standard_refs"] = standard_refs

        elif kind == "plan":
            frontmatter["spec_refs"] = [spec] if spec else []
            frontmatter["request_refs"] = request_refs or []
            frontmatter["work_package_refs"] = []
            if standard_refs:
                frontmatter["standard_refs"] = standard_refs

        elif kind == "task":
            if spec:
                frontmatter["spec_ref"] = spec
            if parent:
                frontmatter["parent_task_ref"] = parent
            if target:
                frontmatter["target"] = target
            if workflow:
                frontmatter["workflow"] = workflow
            if request_refs:
                frontmatter["request_refs"] = request_refs
            if standard_refs:
                frontmatter["standard_refs"] = standard_refs

        elif kind == "wp":
            if plan:
                frontmatter["plan_ref"] = plan
            frontmatter["task_refs"] = []
            if workflow:
                frontmatter["workflow"] = workflow
            if standard_refs:
                frontmatter["standard_refs"] = standard_refs

        elif kind == "standard":
            pass  # Standard only needs id, label, state, summary

        return frontmatter

    def _create_item_with_manager(
        self,
        kind: str,
        id_: str,
        label: str,
        summary: str,
        domain: str | None,
        spec: str | None,
        plan: str | None,
        parent: str | None,
        target: str | None,
        workflow: str | None,
        request_refs: list[str],
        standard_refs: list[str],
        profile: str | None,
        guidance: str | None,
        current_understanding: str | None,
        open_questions: list[str] | None,
        source: str | None,
        context: str | None,
        kind_config: dict,
    ) -> Path:
        """Create item using config-driven approach.

        This method uses configuration to determine item structure, eliminating
        the need for individual manager classes. New kinds can be added by
        updating planning.yaml without code changes.

        Args:
            kind: Planning kind
            id_: Generated ID
            label: Item label
            summary: Item summary
            ... (other fields)
            kind_config: Config dict for this kind

        Returns:
            Path to created item
        """
        has_domain = kind_config.get("has_domain", False)
        effective_domain = domain if has_domain else None

        # Build frontmatter based on kind
        frontmatter = self._build_frontmatter(
            kind=kind,
            id_=id_,
            label=label,
            summary=summary,
            domain=effective_domain,
            spec=spec,
            plan=plan,
            parent=parent,
            target=target,
            workflow=workflow,
            request_refs=request_refs,
            standard_refs=standard_refs,
            profile=profile,
            guidance=guidance,
            current_understanding=current_understanding,
            open_questions=open_questions,
            source=source,
            context=context,
        )

        # Render body template
        body = self.config.document_template(kind, guidance)

        # Get path and create file
        path = self.paths.kind_file(kind, id_, label, effective_domain)
        dump_markdown(path, frontmatter, body)

        # Handle kind-specific post-creation logic
        if kind == "spec" and request_refs:
            self._sync_request_spec_refs(id_, request_refs)

        return path

    def _create_generic_item(
        self,
        kind: str,
        id_: str,
        label: str,
        summary: str,
        kind_config: dict,
        domain: str | None,
    ) -> Path:
        """Create a generic planning item for kinds without dedicated managers.

        This allows new kinds to work immediately after being added to config.

        Args:
            kind: Planning kind
            id_: Generated ID
            label: Item label
            summary: Item summary
            kind_config: Config dict for this kind
            domain: Optional domain

        Returns:
            Path to created item
        """
        item_dir = self.paths.kind_dir(kind, domain)
        item_dir.mkdir(parents=True, exist_ok=True)

        item_path = item_dir / f"{id_}.md"

        frontmatter = {
            "id": id_,
            "kind": kind,
            "label": label,
            "summary": summary,
            "state": "draft",
        }

        if domain:
            frontmatter["domain"] = domain

        body = self.config.document_template(kind) or ""
        dump_markdown(item_path, frontmatter, body)

        return item_path

    def apply_plan_overlay(
        self,
        label: str,
        summary: str,
        spec_id: str,
        task_ids: list[str],
        request_refs: list[str] | None = None,
        domain: str = "core",
    ):
        """Create a plan + WP that wraps existing spec-linked tasks.

        Args:
            label: Plan/WP label
            summary: Plan/WP summary
            spec_id: Specification ID to link plan to
            task_ids: List of task IDs to include in the WP
            request_refs: Optional request references
            domain: Domain for WP (default: core)

        Returns:
            Dict with 'plan' and 'wp' ItemView objects
        """
        plan_id = next_id(self.root, "plan", self.test_mode)
        plan_kind_config = self.config.kind_config("plan")
        self._create_item_with_manager(
            kind="plan",
            id_=plan_id,
            label=label,
            summary=summary,
            domain=None,
            spec=spec_id,
            plan=None,
            parent=None,
            target=None,
            workflow=None,
            request_refs=request_refs or [],
            standard_refs=[],
            profile=None,
            guidance=None,
            current_understanding=None,
            open_questions=None,
            source=None,
            context=None,
            kind_config=plan_kind_config,
        )
        wp_id = next_id(self.root, "wp", self.test_mode)
        wp_kind_config = self.config.kind_config("wp")
        self._create_item_with_manager(
            kind="wp",
            id_=wp_id,
            label=label,
            summary=summary,
            domain=domain,
            spec=None,
            plan=plan_id,
            parent=None,
            target=None,
            workflow=None,
            request_refs=[],
            standard_refs=[],
            profile=None,
            guidance=None,
            current_understanding=None,
            open_questions=None,
            source=None,
            context=None,
            kind_config=wp_kind_config,
        )
        # Manually add task refs to WP frontmatter
        wp_path = self.paths.kind_file("wp", wp_id, label, domain)
        wp_data = parse_markdown(wp_path)
        task_refs = [{"ref": t} for t in task_ids]
        wp_data["frontmatter"]["task_refs"] = task_refs
        dump_markdown(wp_path, wp_data["frontmatter"], wp_data["body"])
        self.index()
        return {"plan": self._find(plan_id), "wp": self._find(wp_id)}

    def create_with_content(
        self,
        kind: str,
        label: str,
        summary: str,
        content: str,
        source: str | None = None,
        domain: str | None = None,
        spec: str | None = None,
        plan: str | None = None,
        parent: str | None = None,
        target: str | None = None,
        workflow: str | None = None,
        request_refs: list[str] | None = None,
        standard_refs: list[str] | None = None,
        check_duplicates: bool = True,
    ):
        """Create planning object with full content.

        Args:
            kind: Object type (plan/request/spec/task/wp/standard)
            label: Object label
            summary: Object summary
            content: Full markdown content (without YAML frontmatter)
            domain: Domain for task/wp
            spec: Spec reference for plan/task
            plan: Plan reference for wp
            parent: Parent task reference
            target: Target reference
            workflow: Workflow name
            request_refs: Request references for spec
        """
        kind = {
            "req": "request",
            "request": "request",
            "sp": "spec",
            "spec": "spec",
            "pl": "plan",
            "plan": "plan",
            "task": "task",
            "wp": "wp",
            "standard": "standard",
        }.get(kind, kind)

        # Apply default standards if not explicitly provided
        if standard_refs is None and kind in {"spec", "task", "plan", "wp", "request"}:
            standard_refs = self.config.standard_defaults_for(kind)
        else:
            standard_refs = standard_refs or []

        if kind in {"request", "spec"} and check_duplicates:
            self._check_duplicate(kind, label, summary)
        if kind in {"spec", "plan", "task"}:
            self._validate_request_refs(request_refs or [])
        if kind == "spec":
            self._require_request_refs_for_spec(request_refs or [])
        if kind == "request" and not source:
            raise ValueError("request requires source to track request origin")
        id_ = self._next_id_for_kind(kind)
        kind_config = self.config.kind_config(kind)

        try:
            path = self._create_item_with_manager(
                kind=kind,
                id_=id_,
                label=label,
                summary=summary,
                domain=domain,
                spec=spec,
                plan=plan,
                parent=parent,
                target=target,
                workflow=workflow,
                request_refs=request_refs or [],
                standard_refs=standard_refs,
                profile=None,
                guidance=None,
                current_understanding=None,
                open_questions=None,
                source=source,
                context=None,
                kind_config=kind_config,
            )
            self.update_content(id_, content)
        except Exception:
            if "path" in locals() and Path(path).exists():
                Path(path).unlink(missing_ok=True)
            raise

        self._publish_event(
            "planning.item.created",
            {"id": id_, "kind": kind, "path": str(path.relative_to(self.root))},
            {"triggered_by": "manual"},
        )

        self.index()
        return self._find(id_)

    def update(
        self,
        id_: str,
        label: str | None = None,
        summary: str | None = None,
        body_append: str | None = None,
    ):
        item = self._find(id_)
        self._assert_not_archived(item, "update")
        data, body = parse_markdown(item.path)
        if label:
            data["label"] = label
        if summary:
            data["summary"] = summary
        if body_append:
            body = body.rstrip() + "\n\n" + body_append.strip() + "\n"
        dump_markdown(item.path, data, body)

        self._publish_event(
            "planning.item.updated",
            {"id": id_, "kind": item.kind},
            {"triggered_by": "manual"},
        )

        self.reconcile()
        return self._find(id_)

    def get_content(self, id_: str) -> str:
        """Get markdown content without YAML frontmatter."""
        item = self._find(id_)
        _, body = parse_markdown(item.path)
        return body

    def update_content(
        self,
        id_: str,
        content: str,
        mode: str = "replace",
        section: str | None = None,
        position: int | None = None,
    ):
        """Update file content with various modes.

        Args:
            id_: Object ID to update
            content: Markdown content to write
            mode: 'replace', 'append', 'insert', or 'section'
            section: Section header to update (for mode='section')
            position: Line position to insert (for mode='insert')
        """
        import re

        item = self._find(id_)
        self._assert_not_archived(item, "update content for")
        data, body = parse_markdown(item.path)

        if mode == "replace":
            body = content.rstrip() + "\n"
        elif mode == "append":
            body = body.rstrip() + "\n\n" + content.rstrip() + "\n"
        elif mode == "insert":
            if position is None:
                raise ValueError("position required for insert mode")
            lines = body.split("\n")
            if position < 1 or position > len(lines) + 1:
                raise ValueError(f"position {position} out of range (1-{len(lines) + 1})")
            lines.insert(position - 1, content.rstrip())
            body = "\n".join(lines) + "\n"
        elif mode == "section":
            if section is None:
                raise ValueError("section header required for section mode")
            # Find section header and content up to next header or end of file
            # Pattern matches: section header, blank line, then content (non-greedy) up to next header or EOF
            section_pattern = re.compile(
                rf"^{re.escape(section)}\n\n(.*?)(?=\n#{1, 6}\s+|$)", re.M | re.S
            )
            match = section_pattern.search(body)
            if not match:
                # Section not found, append it
                body = body.rstrip() + f"\n\n{section}\n\n{content.rstrip()}\n"
            else:
                # Replace section content (keep header and blank line, replace content)
                start = match.start()
                end = match.end()
                body = body[:start] + section + "\n\n" + content.rstrip() + "\n" + body[end:]
        else:
            raise ValueError(f"unknown mode: {mode}")

        dump_markdown(item.path, data, body)

        self._publish_event(
            "planning.item.updated",
            {"id": id_, "kind": item.kind},
            {"triggered_by": "manual"},
        )

        self.reconcile()
        return self._find(id_)

    def move(self, id_: str, domain: str):
        item = self._find(id_)
        self._assert_not_archived(item, "move")
        if item.kind not in {"task", "wp"}:
            raise ValueError("only task/wp can move by domain")
        dest_dir = self.paths.kind_dir(item.kind, domain)
        dest = dest_dir / item.path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item.path), str(dest))
        self.reconcile()
        return self._find(id_)

    def state(
        self,
        id_: str,
        new_state: str,
        reason: str | None = None,
        actor: str | None = None,
        metadata: dict | None = None,
    ):
        item = self._find(id_)
        data, body = parse_markdown(item.path)
        wf_name = data.get("workflow")
        wf = self.config.workflow_for(item.kind, wf_name)
        old = data["state"]
        if new_state not in wf["values"]:
            raise ValueError(f"unknown state {new_state} for workflow")
        if new_state not in wf["transitions"].get(old, []):
            raise ValueError(f"invalid transition {old} -> {new_state}")
        data["state"] = new_state
        timestamp = datetime.now(timezone.utc).isoformat()
        event_payload = {"id": id_, "old_state": old, "new_state": new_state}
        if actor is not None:
            event_payload["actor"] = actor
        if reason is not None:
            event_payload["reason"] = reason
        if new_state == "archived":
            data["archived_at"] = timestamp
            data["archived_by"] = actor or data.get("archived_by") or "system"
            data["archive_reason"] = reason or ""
            data["restored_at"] = None
            data["restored_by"] = None
            event_payload["archived_at"] = data["archived_at"]
            event_payload["archived_by"] = data["archived_by"]
            event_payload["archive_reason"] = data["archive_reason"]
        elif old == "archived":
            data["restored_at"] = timestamp
            data["restored_by"] = actor or "system"
            event_payload["restored_at"] = data["restored_at"]
            event_payload["restored_by"] = data["restored_by"]
        dump_markdown(item.path, data, body)
        if new_state == "archived":
            self.events.emit(f"{item.kind}.archived", event_payload)
            # Cascade archive for request-012
            self._cascade_archive(id_, item.kind, "archived", actor, reason)
        elif new_state == "superseded":
            self.events.emit(f"{item.kind}.superseded", event_payload)
            # Cascade supersede for request-012
            self._cascade_archive(id_, item.kind, "superseded", actor, reason)
        elif old == "archived":
            self.events.emit(f"{item.kind}.restored", event_payload)

        # Cascade close child tasks when request is closed
        if item.kind == "request" and new_state == "closed":
            self._cascade_close_children(id_, item.kind)

        # Publish canonical event (task-0283)
        event_metadata = {"subject": {"kind": item.kind, "id": id_}, "triggered_by": "manual"}
        if metadata:
            event_metadata.update(metadata)

        # Use SYNC mode for all events to ensure propagation completes before state() returns
        mode = DeliveryMode.SYNC
        self._publish_event(
            "planning.item.state.changed",
            event_payload,
            event_metadata,
            mode=mode,
        )

        self.index()

        return self._find(id_)

    def relink(
        self,
        src_id: str,
        field: str,
        dst_id: str,
        seq: int | None = None,
        display: str | None = None,
    ):
        item = self._find(src_id)
        self._assert_not_archived(item, "relink")
        data, body = parse_markdown(item.path)
        if field in {"request_refs", "spec_refs", "standard_refs"}:
            vals = list(data.get(field, []) or [])
            if dst_id not in vals:
                vals.append(dst_id)
            data[field] = vals
        elif field in {"plan_ref", "spec_ref", "parent_task_ref"}:
            data[field] = dst_id
        elif field in {"task_refs", "work_package_refs"}:
            data[field] = Relationships.ensure_rel_list(data.get(field), dst_id, seq, display)
        else:
            raise ValueError(f"unsupported field {field}")
        dump_markdown(item.path, data, body)
        if item.kind == "spec" and field == "request_refs":
            self._sync_request_spec_refs(src_id, [dst_id])
        self.index()
        return self._find(src_id)

    def package(
        self,
        plan_ref: str,
        task_ids: list[str],
        label: str,
        summary: str,
        domain: str = "core",
        workflow: str | None = None,
    ):
        # Check if WP with same label and plan_ref already exists
        existing = None
        for item in self._scan():
            if (
                item.kind == "wp"
                and item.data.get("label") == label
                and item.data.get("plan_ref") == plan_ref
            ):
                existing = item
                break

        if existing:
            # Add tasks to existing WP
            data, body = parse_markdown(existing.path)
            existing_refs = {r["ref"]: r for r in data.get("task_refs", [])}
            seq = max((r["seq"] for r in existing_refs.values()), default=999) + 1000
            for tid in task_ids:
                if tid not in existing_refs:
                    existing_refs[tid] = {"ref": tid, "seq": seq}
                    seq += 1000
            data["task_refs"] = sorted(existing_refs.values(), key=lambda x: x["seq"])
            dump_markdown(existing.path, data, body)
            # Ensure plan has WP ref (for WPs created before fix)
            self._add_wp_ref_to_plan(plan_ref, existing.data["id"])
            self.index()
            return self._find(existing.data["id"])
        else:
            # Create new WP
            item = self.new(
                "wp",
                label=label,
                summary=summary,
                plan=plan_ref,
                domain=domain,
                workflow=workflow,
            )
            data, body = parse_markdown(item.path)
            rels = []
            seq = 1000
            for tid in task_ids:
                rels.append({"ref": tid, "seq": seq})
                seq += 1000
            data["task_refs"] = rels
            dump_markdown(item.path, data, body)
            # Update plan's work_package_refs
            self._add_wp_ref_to_plan(plan_ref, item.data["id"])
            self.index()
            return self._find(item.data["id"])

    def _add_wp_ref_to_plan(self, plan_id: str, wp_id: str):
        """Add work package reference to plan's work_package_refs."""
        plan_item = self._find(plan_id)
        if plan_item and plan_item.kind == "plan":
            data, body = parse_markdown(plan_item.path)
            existing_refs = {r["ref"]: r for r in data.get("work_package_refs", [])}
            if wp_id not in existing_refs:
                seq = max((r["seq"] for r in existing_refs.values()), default=999) + 1000
                existing_refs[wp_id] = {"ref": wp_id, "seq": seq}
                data["work_package_refs"] = sorted(existing_refs.values(), key=lambda x: x["seq"])
                dump_markdown(plan_item.path, data, body)

    def claim(self, kind: str, id_: str, holder: str, ttl: int | None = None):
        rec = self.claims_store.claim(kind, id_, holder, ttl)
        self.events.emit(f"{kind}.claimed", rec)
        self.index()
        return rec

    def unclaim(self, id_: str):
        ok = self.claims_store.unclaim(id_)
        if ok:
            self.events.emit("planning.unclaimed", {"id": id_})
            self.index()
        return ok

    def claims(self, kind: str | None = None):
        claims = self.claims_store.load()["claims"]
        return [c for c in claims if kind is None or c["kind"] == kind]

    def next_items(self, kind: str = "task", state: str = "ready", domain: str | None = None):
        items = [i for i in self._scan() if i.kind == kind and i.data["state"] == state]
        claimed = {c["id"] for c in self.claims()}
        out = []
        for i in items:
            if i.data["id"] in claimed:
                continue
            if i.data.get("deleted"):
                continue
            if domain and i.path.parent.name != domain:
                continue
            out.append(
                {
                    "id": i.data["id"],
                    "label": i.data["label"],
                    "path": str(i.path.relative_to(self.root)),
                }
            )
        return out

    def standards(self, id_: str):
        from .standards import effective_standard_refs

        items = {i.data["id"]: ItemView(i.kind, i.path, i.data, i.body) for i in self._scan()}
        return effective_standard_refs(items[id_], items)

    def dump_all(self, output_dir: str | None = None, format_: str = "json") -> dict:
        """Dump all planning docs to stdout or file.

        Args:
            output_dir: Directory to write files (default: stdout as JSON)
            format_: Output format (json or yaml)

        Returns:
            Summary of what was dumped
        """
        import yaml

        items = self._scan()
        docs = []

        for item in items:
            data, body = parse_markdown(item.path)
            doc = {
                "id": data["id"],
                "kind": item.kind,
                "path": str(item.path.relative_to(self.root)),
                "frontmatter": data,
                "body": body,
            }
            docs.append(doc)

        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)

            dumped = 0
            for doc in docs:
                if format_ == "json":
                    file_path = out_path / f"{doc['id']}.json"
                    file_path.write_text(
                        json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                else:
                    file_path = out_path / f"{doc['id']}.yaml"
                    file_path.write_text(
                        yaml.dump(doc, default_flow_style=False, allow_unicode=True),
                        encoding="utf-8",
                    )
                dumped += 1

            return {"dumped": dumped, "output_dir": str(output_dir), "format": format_}
        else:
            if format_ == "json":
                print_json(docs)
            else:
                print(yaml.dump(docs, default_flow_style=False, allow_unicode=True))

            return {"dumped": len(docs), "output": "stdout", "format": format_}

    def sync_id_counters(self) -> None:
        """Seed persisted counters from existing docs. Run once after install."""
        from ..domain.states import CANONICAL_KINDS
        from .id_gen import sync_counter

        for kind in CANONICAL_KINDS:
            sync_counter(self.root, kind)

    def delete(
        self,
        id_: str,
        hard: bool = False,
        reason: str | None = None,
    ) -> dict:
        item = self._find(id_)
        if hard:
            item.path.unlink(missing_ok=True)
            from .id_gen import sync_counter

            sync_counter(self.root, item.kind)
            self.reconcile()
            result = {
                "id": id_,
                "hard_delete": True,
                "counter_sync": True,
            }
        else:
            data, body = parse_markdown(item.path)
            data["deleted"] = True
            data["deleted_at"] = datetime.now(timezone.utc).isoformat()
            if reason:
                data["deletion_reason"] = reason
            dump_markdown(item.path, data, body)
            self.index()
            result = {
                "id": id_,
                "hard_delete": False,
                "deleted_at": data["deleted_at"],
                "counter_sync": False,
            }
        self._publish_event(
            "planning.item.deleted",
            result,
            {"subject": {"kind": item.kind, "id": id_}, "triggered_by": "manual"},
        )

        return result

    def _validate_request_refs(self, request_refs: list[str]) -> None:
        for req_id in request_refs:
            item = self._find(req_id)
            if item.kind != "request":
                raise ValueError(f"request '{req_id}' does not exist")

    def _require_request_refs_for_spec(self, request_refs: list[str]) -> None:
        if not request_refs:
            raise ValueError("spec requires at least one request reference")

    def _cascade_archive(
        self, id_: str, kind: str, new_state: str, actor: str | None, reason: str | None
    ) -> None:
        """Cascade archive to downstream items solely owned by the archived item.

        Implements request-012 cascade archive:
        - Archiving a request → archive specs whose only active request ref is this request
        - Archiving a spec → archive plans/tasks/WPs whose only active spec ref is this spec

        Args:
            id_: ID of the item being archived
            kind: Kind of the item being archived (request, spec, etc.)
            new_state: The terminal state (archived, superseded)
            actor: Who triggered the archive
            reason: Reason for the archive
        """
        if kind == "request":
            # Find specs that solely reference this request
            for item in self._scan():
                if item.kind != "spec" or item.data.get("state") in (
                    "archived",
                    "deleted",
                    "superseded",
                ):
                    continue
                request_refs = item.data.get("request_refs", []) or []
                # Check if this request is the only active request ref
                active_refs = [ref for ref in request_refs if not self._is_terminal(ref)]
                if len(active_refs) == 1 and active_refs[0] == id_:
                    # Cascade archive this spec
                    try:
                        self.state(
                            item.data["id"], new_state, reason=f"Cascaded from {id_}", actor=actor
                        )
                    except Exception:
                        pass  # Silently skip if cascade fails
        elif kind == "spec":
            # Find plans/tasks/WPs that solely reference this spec
            for item in self._scan():
                if item.kind not in ("plan", "task", "wp"):
                    continue
                if item.data.get("state") in ("archived", "deleted", "superseded"):
                    continue
                spec_ref = item.data.get("spec_ref")
                if spec_ref == id_ and not self._is_terminal(id_):
                    # Cascade archive this item
                    try:
                        self.state(
                            item.data["id"], new_state, reason=f"Cascaded from {id_}", actor=actor
                        )
                    except Exception:
                        pass  # Silently skip if cascade fails

    def _cascade_close_children(self, id_: str, kind: str) -> None:
        """Cascade close to child tasks when a request is closed.

        Implements request lifecycle closure: when a request is closed, all child tasks
        and specs that solely belong to it should also be closed.

        Args:
            id_: ID of the request being closed
            kind: Always "request"
        """
        if kind != "request":
            return

        # Find tasks that solely reference this request
        for item in self._scan():
            if item.kind == "task":
                if item.data.get("state") in ("closed", "archived", "deleted", "superseded"):
                    continue
                request_refs = item.data.get("request_refs", []) or []
                active_refs = [ref for ref in request_refs if not self._is_terminal(ref)]
                if len(active_refs) == 1 and active_refs[0] == id_:
                    try:
                        self.state(
                            item.data["id"], "closed", reason=f"Cascade from request close: {id_}"
                        )
                    except Exception:
                        pass  # Silently skip if cascade fails
            elif item.kind == "spec":
                if item.data.get("state") in ("closed", "archived", "deleted", "superseded"):
                    continue
                request_refs = item.data.get("request_refs", []) or []
                active_refs = [ref for ref in request_refs if not self._is_terminal(ref)]
                if len(active_refs) == 1 and active_refs[0] == id_:
                    try:
                        self.state(
                            item.data["id"], "closed", reason=f"Cascade from request close: {id_}"
                        )
                    except Exception:
                        pass  # Silently skip if cascade fails

    def _is_terminal(self, id_: str) -> bool:
        """Check if an item is in a terminal state (archived, deleted, superseded)."""
        try:
            item = self._find(id_)
            return item.data.get("state") in ("archived", "deleted", "superseded")
        except KeyError:
            return True  # Treat missing items as terminal

    def _auto_supersede(self, superseded_id: str, new_id: str) -> None:
        """Auto-supersede an existing request when creating a refinement.

        Args:
            superseded_id: ID of the request to supersede
            new_id: ID of the new request that supersedes it
        """
        try:
            superseded = self._find(superseded_id)
        except KeyError:
            # Old request doesn't exist, just create new one
            return

        try:
            self.state(superseded_id, "superseded", reason=f"Auto-superseded by {new_id}")
        except ValueError as e:
            # If state transition is invalid, still add the metadata
            # but don't change state
            pass

        try:
            data, body = parse_markdown(superseded.path)
        except Exception:
            return

        # Add bidirectional fields
        if "meta" not in data:
            data["meta"] = {}
        data["meta"]["superseded_by"] = new_id

        # Add note to body
        note = f"\n\n**Superseded by** `{new_id}` on {datetime.now(timezone.utc).isoformat()}"
        if "# Notes" in body:
            body = body.rstrip() + note + "\n"
        else:
            body = body.rstrip() + "\n\n# Notes\n\n" + note + "\n"

        dump_markdown(superseded.path, data, body)

        # Add supersedes field to new request
        new_item = self._find(new_id)
        new_data, new_body = parse_markdown(new_item.path)
        if "meta" not in new_data:
            new_data["meta"] = {}
        new_data["meta"]["supersedes"] = superseded_id

        dump_markdown(new_item.path, new_data, new_body)

        # Re-index both
        self.index()

    def _check_duplicate(self, kind: str, label: str, summary: str) -> None:
        label_key = label.strip().lower()
        for item in self._scan():
            if item.kind != kind or item.data.get("deleted"):
                continue
            existing_label = str(item.data.get("label", "")).strip().lower()
            if existing_label == label_key:
                raise ValueError(
                    f"{kind} already exists: {item.data['id']} ({item.data.get('label', '')})"
                )
