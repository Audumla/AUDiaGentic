from __future__ import annotations
from .base_mgr import BaseMgr
from ..fs.write import dump_markdown

class SpecMgr(BaseMgr):
    def create(self, id_: str, label: str, summary: str, request_refs=None, state: str = 'draft'):
        path = self.path_for('spec', id_, label)
        data = {
            'id': id_,
            'label': label,
            'state': state,
            'summary': summary,
            'request_refs': request_refs or [],
            'task_refs': [],
        }
        body = '# Purpose\n\n\n# Scope\n\n\n# Requirements\n\n\n# Constraints\n\n\n# Acceptance Criteria\n\n'
        dump_markdown(path, data, body)
        return path
