from __future__ import annotations
from .base_mgr import BaseMgr
from ..fs.write import dump_markdown

class PlanMgr(BaseMgr):
    def create(
        self,
        id_: str,
        label: str,
        summary: str,
        spec_refs,
        request_refs=None,
        state: str = 'draft',
    ):
        path = self.path_for('plan', id_, label)
        data = {
            'id': id_,
            'label': label,
            'state': state,
            'summary': summary,
            'spec_refs': spec_refs,
            'request_refs': request_refs or [],
            'work_package_refs': [],
        }
        body = '# Objectives\n\n\n# Delivery Approach\n\n\n# Dependencies\n\n'
        dump_markdown(path, data, body)
        return path
