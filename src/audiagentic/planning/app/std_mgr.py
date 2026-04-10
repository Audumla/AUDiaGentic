from __future__ import annotations
from .base_mgr import BaseMgr
from ..fs.write import dump_markdown

class StandardMgr(BaseMgr):
    def create(self, id_: str, label: str, summary: str, state: str = 'ready'):
        path = self.path_for('standard', id_, label)
        data = {'id': id_, 'label': label, 'state': state, 'summary': summary}
        body = '# Standard\n\n\n# Requirements\n\n'
        dump_markdown(path, data, body)
        return path
