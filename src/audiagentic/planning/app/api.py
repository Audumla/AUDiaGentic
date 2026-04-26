from __future__ import annotations

from pathlib import Path

from ..fs.scan import scan_items
from .api_types import ItemView
from .claims import Claims
from .compact_mgr import Compactor
from .config import Config
from .events import EventLog
from .ext_mgr import Extracts
from .idx_mgr import Indexer
from .paths import Paths
from .rec_mgr import Reconcile
from .rel_config import RelationshipConfig
from .services.content_service import ContentService
from .services.event_service import EventService
from .services.frontmatter_builder import FrontmatterBuilder
from .services.item_creator import ItemCreatorService
from .services.item_reader import ItemReaderService
from .services.lifecycle_service import LifecycleService
from .services.maintenance_service import MaintenanceService
from .services.planning_supersede import PlanningSupersedeService
from .services.policy_service import PolicyService
from .services.queue_service import QueueService
from .services.relationship_service import RelationshipService
from .services.workflow_actions_service import WorkflowActionsService
from .val_mgr import Validator


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
        self.relationship_config = RelationshipConfig(self.config)
        self.extracts = Extracts(self.root, api_getter=lambda: self)
        self.reconciler = Reconcile(self.root)
        self.compactor = Compactor(self.root)
        self.reader = ItemReaderService(self)
        self.maintenance = MaintenanceService(self)
        self.frontmatter_builder = FrontmatterBuilder(self.config)
        self.creator = ItemCreatorService(self)
        self.relationships = RelationshipService(self)
        self.lifecycle = LifecycleService(self)
        self.policy = PolicyService(self)
        self.planning_supersede = PlanningSupersedeService(self)
        self.content = ContentService(self)
        self.queue = QueueService(self)
        self.workflow_actions = WorkflowActionsService(self)
        self.event_service = EventService(self)
        self.event_service.initialize()
        self._propagation_engine = self.event_service.propagation_engine
        self._propagation_subscription = self.event_service.propagation_subscription

    def _scan(self):
        return scan_items(self.root)

    def _publish_event(
        self,
        event_type: str,
        payload: dict,
        metadata: dict | None = None,
        mode=None,
    ) -> None:
        self.event_service.publish_event(event_type, payload, metadata=metadata, mode=mode)

    def _on_state_change_for_propagation(
        self,
        event_type: str,
        payload: dict,
        metadata: dict,
    ) -> None:
        self.event_service.on_state_change_for_propagation(event_type, payload, metadata)

    def lookup(self, id_: str) -> ItemView:
        return self.reader.lookup(id_)

    def head(self, id_: str) -> dict[str, object]:
        return self.reader.head(id_)

    def _find(self, id_: str):
        return self.reader.find(id_)

    def validate(self, raise_on_error: bool = False):
        return self.maintenance.validate(raise_on_error=raise_on_error)

    def index(self):
        self.maintenance.index()

    def rebaseline(self) -> dict:
        return self.maintenance.rebaseline()

    def clean_indexes(self) -> dict:
        return self.maintenance.clean_indexes()

    def maintain(self) -> dict:
        return self.maintenance.maintain()

    def compact(self) -> dict:
        return self.maintenance.compact()

    def reconcile(self):
        return self.maintenance.reconcile()

    def new(
        self,
        kind: str,
        label: str,
        summary: str,
        domain: str | None = None,
        workflow: str | None = None,
        refs: dict[str, object] | None = None,
        fields: dict[str, object] | None = None,
        profile: str | None = None,
        guidance: str | None = None,
        current_understanding: str | None = None,
        open_questions: list[str] | None = None,
        source: str | None = None,
        context: str | None = None,
        check_duplicates: bool = True,
    ) -> ItemView:
        return self.creator.new(
            kind=kind,
            label=label,
            summary=summary,
            domain=domain,
            workflow=workflow,
            refs=refs,
            fields=fields,
            profile=profile,
            guidance=guidance,
            current_understanding=current_understanding,
            open_questions=open_questions,
            source=source,
            context=context,
            check_duplicates=check_duplicates,
        )

    def apply_plan_overlay(
        self,
        label: str,
        summary: str,
        spec_id: str,
        task_ids: list[str],
        request_refs: list[str] | None = None,
        domain: str | None = None,
    ):
        return self.workflow_actions.apply_plan_overlay(
            label=label,
            summary=summary,
            spec_id=spec_id,
            task_ids=task_ids,
            request_refs=request_refs,
            domain=domain,
        )

    def create_with_content(
        self,
        kind: str,
        label: str,
        summary: str,
        content: str,
        source: str | None = None,
        domain: str | None = None,
        workflow: str | None = None,
        refs: dict[str, object] | None = None,
        fields: dict[str, object] | None = None,
        check_duplicates: bool = True,
    ):
        """Create planning object with full content.

        Args:
            kind: Configured planning object type
            label: Object label
            summary: Object summary
            content: Full markdown content (without YAML frontmatter)
            domain: Optional configured domain value
            refs: Input refs keyed by names from planning.creation.seed_reference_fields
            fields: Extra frontmatter fields
            workflow: Workflow name
        """
        return self.creator.create_with_content(
            kind=kind,
            label=label,
            summary=summary,
            content=content,
            source=source,
            domain=domain,
            workflow=workflow,
            refs=refs,
            fields=fields,
            check_duplicates=check_duplicates,
        )

    def update(
        self,
        id_: str,
        label: str | None = None,
        summary: str | None = None,
        body_append: str | None = None,
    ):
        return self.content.update(id_, label=label, summary=summary, body_append=body_append)

    def get_content(self, id_: str) -> str:
        return self.content.get_content(id_)

    def update_content(
        self,
        id_: str,
        content: str,
        mode: str = "replace",
        section: str | None = None,
        position: int | None = None,
    ):
        return self.content.update_content(
            id_,
            content,
            mode=mode,
            section=section,
            position=position,
        )

    def move(self, id_: str, domain: str):
        return self.content.move(id_, domain)

    def state(
        self,
        id_: str,
        new_state: str,
        reason: str | None = None,
        actor: str | None = None,
        metadata: dict | None = None,
    ):
        return self.lifecycle.state(id_, new_state, reason=reason, actor=actor, metadata=metadata)

    def relink(
        self,
        src_id: str,
        field: str,
        dst_id: str,
        seq: int | None = None,
        display: str | None = None,
    ):
        return self.relationships.relink(src_id, field, dst_id, seq=seq, display=display)

    def package(
        self,
        plan_ref: str,
        task_ids: list[str],
        label: str,
        summary: str,
        domain: str | None = None,
        workflow: str | None = None,
    ):
        return self.workflow_actions.package(
            plan_ref=plan_ref,
            task_ids=task_ids,
            label=label,
            summary=summary,
            domain=domain,
            workflow=workflow,
        )

    def claim(self, kind: str, id_: str, holder: str, ttl: int | None = None):
        return self.queue.claim(kind, id_, holder, ttl)

    def unclaim(self, id_: str):
        return self.queue.unclaim(id_)

    def claims(self, kind: str | None = None):
        return self.queue.claims(kind)

    def next_items(
        self, kind: str | None = None, state: str | None = None, domain: str | None = None
    ):
        return self.queue.next_items(kind=kind, state=state, domain=domain)

    def effective_refs(self, id_: str, field: str | None = None):
        return self.workflow_actions.effective_refs(id_, field=field)

    def dump_all(self, output_dir: str | None = None, format_: str = "json") -> dict:
        return self.workflow_actions.dump_all(output_dir=output_dir, format_=format_)

    def sync_id_counters(self) -> None:
        """Seed persisted counters from existing docs. Run once after install."""
        from .id_gen import sync_counter

        for kind in self.config.all_kinds():
            sync_counter(self.root, kind)

    def delete(
        self,
        id_: str,
        hard: bool = False,
        reason: str | None = None,
    ) -> dict:
        return self.content.delete(id_, hard=hard, reason=reason)
