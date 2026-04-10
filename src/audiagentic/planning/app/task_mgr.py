from __future__ import annotations
from .base_mgr import BaseMgr
from ..fs.write import dump_markdown

class TaskMgr(BaseMgr):
    def create(
        self,
        id_: str,
        label: str,
        summary: str,
        spec_ref: str,
        domain: str = 'core',
        state: str = 'draft',
        parent_task_ref: str | None = None,
        target: str | None = None,
        workflow: str | None = None,
        request_refs=None,
    ):
        path = self.path_for('task', id_, label, domain)
        data = {'id': id_, 'label': label, 'state': state, 'summary': summary, 'spec_ref': spec_ref}
        if parent_task_ref:
            data['parent_task_ref'] = parent_task_ref
        if target:
            data['target'] = target
        if workflow:
            data['workflow'] = workflow
        if request_refs is not None:
            data['request_refs'] = request_refs
        body = '# Description\n\n\n# Acceptance Criteria\n\n\n# Notes\n\n'
        dump_markdown(path, data, body)
        return path
