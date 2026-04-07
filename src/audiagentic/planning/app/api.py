from __future__ import annotations
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
        self.events = EventLog(self.root / '.audiagentic/planning/events/events.jsonl')
        self.claims_store = Claims(self.root / '.audiagentic/planning/claims/claims.json')
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
            if item.data['id'] == id_:
                return item
        raise KeyError(id_)

    def validate(self, raise_on_error: bool = False):
        errors = self.validator.validate_all()
        if raise_on_error and errors:
            raise RuntimeError('\n'.join(errors))
        return errors

    def index(self):
        self.indexer.write_indexes()

    def reconcile(self):
        result = self.reconciler.run()
        self.index()
        self.hooks.run('after_reconcile', 'planning', {'orphans': result['orphans']})
        return result

    def new(self, kind: str, label: str, summary: str, domain: str | None = None, spec: str | None = None, plan: str | None = None, parent: str | None = None, target: str | None = None, workflow: str | None = None, request_refs: list[str] | None = None):
        kind = {'req': 'request', 'request': 'request', 'sp': 'spec', 'spec': 'spec', 'pl': 'plan', 'plan': 'plan', 'task': 'task', 'wp': 'wp', 'standard': 'standard'}.get(kind, kind)
        self.hooks.run('before_create', kind, {'label': label})
        id_ = next_id(self.root, kind)
        if kind == 'request':
            path = self.req_mgr.create(id_, label, summary)
        elif kind == 'spec':
            path = self.spec_mgr.create(id_, label, summary, request_refs=request_refs or [])
        elif kind == 'plan':
            path = self.plan_mgr.create(id_, label, summary, spec_refs=[spec] if spec else [])
        elif kind == 'task':
            if not spec:
                raise ValueError('task requires --spec')
            path = self.task_mgr.create(id_, label, summary, spec_ref=spec, domain=domain or 'core', parent_task_ref=parent, target=target, workflow=workflow)
        elif kind == 'wp':
            if not plan:
                raise ValueError('wp requires --plan')
            path = self.wp_mgr.create(id_, label, summary, plan_ref=plan, task_refs=[], domain=domain or 'core', workflow=workflow)
        elif kind == 'standard':
            path = self.std_mgr.create(id_, label, summary)
        else:
            raise ValueError(kind)
        self.hooks.run('after_create', kind, {'id': id_, 'path': str(path.relative_to(self.root))})
        self.index()
        return self._find(id_)

    def update(self, id_: str, label: str | None = None, summary: str | None = None, body_append: str | None = None):
        item = self._find(id_)
        self.hooks.run('before_update', item.kind, {'id': id_})
        data, body = parse_markdown(item.path)
        if label:
            data['label'] = label
        if summary:
            data['summary'] = summary
        if body_append:
            body = body.rstrip() + '\n\n' + body_append.strip() + '\n'
        dump_markdown(item.path, data, body)
        self.hooks.run('after_update', item.kind, {'id': id_})
        self.reconcile()
        return self._find(id_)

    def move(self, id_: str, domain: str):
        item = self._find(id_)
        if item.kind not in {'task', 'wp'}:
            raise ValueError('only task/wp can move by domain')
        dest_dir = self.paths.kind_dir(item.kind, domain)
        dest = dest_dir / item.path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item.path), str(dest))
        self.reconcile()
        return self._find(id_)

    def state(self, id_: str, new_state: str):
        item = self._find(id_)
        data, body = parse_markdown(item.path)
        wf_name = data.get('workflow')
        wf = self.config.workflow_for(item.kind, wf_name)
        old = data['state']
        if new_state not in wf['values']:
            raise ValueError(f'unknown state {new_state} for workflow')
        if new_state not in wf['transitions'].get(old, []):
            raise ValueError(f'invalid transition {old} -> {new_state}')
        self.hooks.run('before_state_change', item.kind, {'id': id_, 'old_state': old, 'new_state': new_state})
        data['state'] = new_state
        dump_markdown(item.path, data, body)
        self.hooks.run('after_state_change', item.kind, {'id': id_, 'old_state': old, 'new_state': new_state})
        self.index()
        return self._find(id_)

    def relink(self, src_id: str, field: str, dst_id: str, seq: int | None = None, display: str | None = None):
        item = self._find(src_id)
        data, body = parse_markdown(item.path)
        if field in {'request_refs', 'spec_refs', 'standard_refs'}:
            vals = list(data.get(field, []) or [])
            if dst_id not in vals:
                vals.append(dst_id)
            data[field] = vals
        elif field in {'plan_ref', 'spec_ref', 'parent_task_ref'}:
            data[field] = dst_id
        elif field in {'task_refs', 'work_package_refs'}:
            data[field] = Relationships.ensure_rel_list(data.get(field), dst_id, seq, display)
        else:
            raise ValueError(f'unsupported field {field}')
        dump_markdown(item.path, data, body)
        self.index()
        return self._find(src_id)

    def package(self, plan_ref: str, task_ids: list[str], label: str, summary: str, domain: str = 'core', workflow: str | None = None):
        item = self.new('wp', label=label, summary=summary, plan=plan_ref, domain=domain, workflow=workflow)
        data, body = parse_markdown(item.path)
        rels = []
        seq = 1000
        for tid in task_ids:
            rels.append({'ref': tid, 'seq': seq})
            seq += 1000
        data['task_refs'] = rels
        dump_markdown(item.path, data, body)
        self.index()
        return self._find(item.data['id'])

    def claim(self, kind: str, id_: str, holder: str, ttl: int | None = None):
        rec = self.claims_store.claim(kind, id_, holder, ttl)
        self.events.emit(f'{kind}.claimed', rec)
        self.index()
        return rec

    def unclaim(self, id_: str):
        ok = self.claims_store.unclaim(id_)
        if ok:
            self.events.emit('planning.unclaimed', {'id': id_})
            self.index()
        return ok

    def claims(self, kind: str | None = None):
        claims = self.claims_store.load()['claims']
        return [c for c in claims if kind is None or c['kind'] == kind]

    def next_items(self, kind: str = 'task', state: str = 'ready', domain: str | None = None):
        items = [i for i in self._scan() if i.kind == kind and i.data['state'] == state]
        claimed = {c['id'] for c in self.claims()}
        out = []
        for i in items:
            if i.data['id'] in claimed:
                continue
            if domain and i.path.parent.name != domain:
                continue
            out.append({'id': i.data['id'], 'label': i.data['label'], 'path': str(i.path.relative_to(self.root))})
        return out

    def standards(self, id_: str):
        from .standards import effective_standard_refs
        items = {i.data['id']: ItemView(i.kind, i.path, i.data, i.body) for i in self._scan()}
        return effective_standard_refs(items[id_], items)

    def hooks_info(self):
        return self.config.hooks

    def sync_id_counters(self) -> None:
        """Seed persisted counters from existing docs. Run once after install."""
        from .id_gen import sync_counter
        from ..domain.states import CANONICAL_KINDS
        for kind in CANONICAL_KINDS:
            sync_counter(self.root, kind)
