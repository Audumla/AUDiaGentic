from __future__ import annotations
from .base_mgr import BaseMgr
from ..fs.write import dump_markdown

class WPMgr(BaseMgr):
    def create(self, id_: str, label: str, summary: str, plan_ref: str, task_refs, domain: str = 'core', state: str = 'draft', workflow: str | None = None, standard_refs=None):
        path = self.path_for('wp', id_, label, domain)
        data = {'id': id_, 'label': label, 'state': state, 'summary': summary, 'plan_ref': plan_ref, 'task_refs': task_refs}
        if workflow:
            data['workflow'] = workflow
        if standard_refs:
            data['standard_refs'] = standard_refs
        body = '# Objective\n\n\n# Scope of This Package\n\n\n# Inputs\n\n\n# Instructions\n\n\n# Required Outputs\n\n\n# Acceptance Checks\n\n\n# Non-Goals\n\n'
        dump_markdown(path, data, body)
        return path
