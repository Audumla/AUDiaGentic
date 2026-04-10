from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import shutil
from ..fs.scan import scan_items
from ..fs.read import parse_markdown
from ..fs.write import dump_markdown
from .config import Config
from .paths import Paths
from .events import EventLog
from .claims import Claims
from .hook_mgr import Hooks
from .idx_mgr import Indexer
from .val_mgr import Validator
from .ext_mgr import Extracts
from .rec_mgr import Reconcile
from .req_mgr import RequestMgr
from .spec_mgr import SpecMgr
from .plan_mgr import PlanMgr
from .task_mgr import TaskMgr
from .wp_mgr import WPMgr
from .std_mgr import StandardMgr
from .rel_mgr import Relationships
from .api_types import ItemView
from .id_gen import next_id


class PlanningAPI:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.config = Config(self.root)
        self.paths = Paths(self.root)
        self.events = EventLog(self.root / ".audiagentic/planning/events/events.jsonl")
        self.claims_store = Claims(
            self.root / ".audiagentic/planning/claims/claims.json"
        )
        self.indexer = Indexer(self.root)
        self.validator = Validator(self.root)
        self.extracts = Extracts(self.root)
        self.reconciler = Reconcile(self.root)
        self.hooks = Hooks(self.root, api_getter=lambda: self)
        self.req_mgr = RequestMgr(self.root)
        self.spec_mgr = SpecMgr(self.root)
        self.plan_mgr = PlanMgr(self.root)
        self.task_mgr = TaskMgr(self.root)
        self.wp_mgr = WPMgr(self.root)
        self.std_mgr = StandardMgr(self.root)

    def _scan(self):
        return scan_items(self.root)

    def _find(self, id_: str):
        for item in self._scan():
            if item.data["id"] == id_:
                return item
        raise KeyError(id_)

    def validate(self, raise_on_error: bool = False):
        errors = self.validator.validate_all()
        if raise_on_error and errors:
            raise RuntimeError("\n".join(errors))
        return errors

    def index(self):
        self.indexer.write_indexes()

    def reconcile(self):
        result = self.reconciler.run()
        self.index()
        self.hooks.run("after_reconcile", "planning", {"orphans": result["orphans"]})
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
        profile: str | None = None,
        current_understanding: str | None = None,
        open_questions: list[str] | None = None,
        source: str | None = None,
        context: str | None = None,
        check_duplicates: bool = True,
    ):
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
        self.hooks.run("before_create", kind, {"label": label})
        if kind in {"request", "spec"} and check_duplicates:
            self._check_duplicate(kind, label, summary)
        if kind in {"spec", "plan", "task"}:
            self._validate_request_refs(request_refs or [])
        id_ = next_id(self.root, kind)
        if kind == "request":
            path = self.req_mgr.create(
                id_,
                label,
                summary,
                profile=profile,
                current_understanding=current_understanding,
                open_questions=open_questions,
                source=source,
                context=context,
            )
            # Apply profile cascade if specified
            if profile:
                prof = self.config.profile_for(profile)
                if "specification" in prof.get("on_request_create", []):
                    spec_id = next_id(self.root, "spec")
                    self.spec_mgr.create(
                        spec_id,
                        f"{label} — Specification",
                        f"Specification for {summary}",
                        request_refs=[id_],
                    )
        elif kind == "spec":
            try:
                path = self.spec_mgr.create(
                    id_, label, summary, request_refs=request_refs or []
                )
            except Exception:
                if "path" in locals() and Path(path).exists():
                    Path(path).unlink(missing_ok=True)
                raise
        elif kind == "plan":
            try:
                path = self.plan_mgr.create(
                    id_,
                    label,
                    summary,
                    spec_refs=[spec] if spec else [],
                    request_refs=request_refs or [],
                )
            except Exception:
                if "path" in locals() and Path(path).exists():
                    Path(path).unlink(missing_ok=True)
                raise
        elif kind == "task":
            if not spec:
                raise ValueError("task requires --spec")
            try:
                path = self.task_mgr.create(
                    id_,
                    label,
                    summary,
                    spec_ref=spec,
                    domain=domain or "core",
                    parent_task_ref=parent,
                    target=target,
                    workflow=workflow,
                    request_refs=request_refs or [],
                )
            except Exception:
                if "path" in locals() and Path(path).exists():
                    Path(path).unlink(missing_ok=True)
                raise
        elif kind == "wp":
            if not plan:
                raise ValueError("wp requires --plan")
            path = self.wp_mgr.create(
                id_,
                label,
                summary,
                plan_ref=plan,
                task_refs=[],
                domain=domain or "core",
                workflow=workflow,
            )
        elif kind == "standard":
            path = self.std_mgr.create(id_, label, summary)
        else:
            raise ValueError(kind)
        self.hooks.run(
            "after_create", kind, {"id": id_, "path": str(path.relative_to(self.root))}
        )
        self.index()
        return self._find(id_)

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
        plan_id = next_id(self.root, "plan")
        self.plan_mgr.create(
            plan_id,
            label,
            summary,
            spec_refs=[spec_id],
            request_refs=request_refs or [],
        )
        wp_id = next_id(self.root, "wp")
        task_refs = [{"ref": t} for t in task_ids]
        self.wp_mgr.create(
            wp_id,
            label,
            summary,
            plan_ref=plan_id,
            task_refs=task_refs,
            domain=domain,
        )
        self.index()
        return {"plan": self._find(plan_id), "wp": self._find(wp_id)}

    def create_with_content(
        self,
        kind: str,
        label: str,
        summary: str,
        content: str,
        domain: str | None = None,
        spec: str | None = None,
        plan: str | None = None,
        parent: str | None = None,
        target: str | None = None,
        workflow: str | None = None,
        request_refs: list[str] | None = None,
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
        self.hooks.run("before_create", kind, {"label": label})
        if kind in {"request", "spec"} and check_duplicates:
            self._check_duplicate(kind, label, summary)
        if kind in {"spec", "plan", "task"}:
            self._validate_request_refs(request_refs or [])
        id_ = next_id(self.root, kind)
        if kind == "request":
            path = self.req_mgr.create(id_, label, summary)
            self.update_content(id_, content)
        elif kind == "spec":
            try:
                path = self.spec_mgr.create(
                    id_, label, summary, request_refs=request_refs or []
                )
                self.update_content(id_, content)
            except Exception:
                if "path" in locals() and Path(path).exists():
                    Path(path).unlink(missing_ok=True)
                raise
        elif kind == "plan":
            try:
                path = self.plan_mgr.create(
                    id_,
                    label,
                    summary,
                    spec_refs=[spec] if spec else [],
                    request_refs=request_refs or [],
                )
                self.update_content(id_, content)
            except Exception:
                if "path" in locals() and Path(path).exists():
                    Path(path).unlink(missing_ok=True)
                raise
        elif kind == "task":
            if not spec:
                raise ValueError("task requires --spec")
            try:
                path = self.task_mgr.create(
                    id_,
                    label,
                    summary,
                    spec_ref=spec,
                    domain=domain or "core",
                    parent_task_ref=parent,
                    target=target,
                    workflow=workflow,
                    request_refs=request_refs or [],
                )
                self.update_content(id_, content)
            except Exception:
                if "path" in locals() and Path(path).exists():
                    Path(path).unlink(missing_ok=True)
                raise
        elif kind == "wp":
            if not plan:
                raise ValueError("wp requires --plan")
            path = self.wp_mgr.create(
                id_,
                label,
                summary,
                plan_ref=plan,
                task_refs=[],
                domain=domain or "core",
                workflow=workflow,
            )
            self.update_content(id_, content)
        elif kind == "standard":
            path = self.std_mgr.create(id_, label, summary)
            self.update_content(id_, content)
        else:
            raise ValueError(kind)
        self.hooks.run(
            "after_create", kind, {"id": id_, "path": str(path.relative_to(self.root))}
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
        self.hooks.run("before_update", item.kind, {"id": id_})
        data, body = parse_markdown(item.path)
        if label:
            data["label"] = label
        if summary:
            data["summary"] = summary
        if body_append:
            body = body.rstrip() + "\n\n" + body_append.strip() + "\n"
        dump_markdown(item.path, data, body)
        self.hooks.run("after_update", item.kind, {"id": id_})
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
        self.hooks.run("before_update", item.kind, {"id": id_})
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
                raise ValueError(
                    f"position {position} out of range (1-{len(lines) + 1})"
                )
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
                body = (
                    body[:start]
                    + section
                    + "\n\n"
                    + content.rstrip()
                    + "\n"
                    + body[end:]
                )
            match = section_pattern.search(body)
            if not match:
                # Section not found, append it
                body = body.rstrip() + f"\n\n{section}\n{content.rstrip()}\n"
            else:
                # Replace section content
                start = match.start()
                end = match.end()
                body = (
                    body[:start] + section + "\n" + content.rstrip() + "\n" + body[end:]
                )
        else:
            raise ValueError(f"unknown mode: {mode}")

        dump_markdown(item.path, data, body)
        self.hooks.run("after_update", item.kind, {"id": id_})
        self.reconcile()
        return self._find(id_)

    def move(self, id_: str, domain: str):
        item = self._find(id_)
        if item.kind not in {"task", "wp"}:
            raise ValueError("only task/wp can move by domain")
        dest_dir = self.paths.kind_dir(item.kind, domain)
        dest = dest_dir / item.path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item.path), str(dest))
        self.reconcile()
        return self._find(id_)

    def state(self, id_: str, new_state: str):
        item = self._find(id_)
        data, body = parse_markdown(item.path)
        wf_name = data.get("workflow")
        wf = self.config.workflow_for(item.kind, wf_name)
        old = data["state"]
        if new_state not in wf["values"]:
            raise ValueError(f"unknown state {new_state} for workflow")
        if new_state not in wf["transitions"].get(old, []):
            raise ValueError(f"invalid transition {old} -> {new_state}")
        self.hooks.run(
            "before_state_change",
            item.kind,
            {"id": id_, "old_state": old, "new_state": new_state},
        )
        data["state"] = new_state
        dump_markdown(item.path, data, body)
        self.hooks.run(
            "after_state_change",
            item.kind,
            {"id": id_, "old_state": old, "new_state": new_state},
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
        data, body = parse_markdown(item.path)
        if field in {"request_refs", "spec_refs", "standard_refs"}:
            vals = list(data.get(field, []) or [])
            if dst_id not in vals:
                vals.append(dst_id)
            data[field] = vals
        elif field in {"plan_ref", "spec_ref", "parent_task_ref"}:
            data[field] = dst_id
        elif field in {"task_refs", "work_package_refs"}:
            data[field] = Relationships.ensure_rel_list(
                data.get(field), dst_id, seq, display
            )
        else:
            raise ValueError(f"unsupported field {field}")
        dump_markdown(item.path, data, body)
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
            self.index()
            return self._find(item.data["id"])

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

    def next_items(
        self, kind: str = "task", state: str = "ready", domain: str | None = None
    ):
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

        items = {
            i.data["id"]: ItemView(i.kind, i.path, i.data, i.body) for i in self._scan()
        }
        return effective_standard_refs(items[id_], items)

    def hooks_info(self):
        return self.config.hooks

    def sync_id_counters(self) -> None:
        """Seed persisted counters from existing docs. Run once after install."""
        from .id_gen import sync_counter
        from ..domain.states import CANONICAL_KINDS

        for kind in CANONICAL_KINDS:
            sync_counter(self.root, kind)

    def delete(
        self,
        id_: str,
        hard: bool = False,
        reason: str | None = None,
    ) -> dict:
        item = self._find(id_)
        self.hooks.run(
            "before_delete", item.kind, {"id": id_, "hard": hard, "reason": reason}
        )
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
        self.hooks.run("after_delete", item.kind, result)
        return result

    def _validate_request_refs(self, request_refs: list[str]) -> None:
        for req_id in request_refs:
            item = self._find(req_id)
            if item.kind != "request":
                raise ValueError(f"request '{req_id}' does not exist")

    def _check_duplicate(self, kind: str, label: str, summary: str) -> None:
        label_key = label.strip().lower()
        for item in self._scan():
            if item.kind != kind or item.data.get("deleted"):
                continue
            existing_label = str(item.data.get("label", "")).strip().lower()
            if existing_label == label_key:
                raise ValueError(
                    f"{kind} already exists: {item.data['id']} "
                    f"({item.data.get('label', '')})"
                )
