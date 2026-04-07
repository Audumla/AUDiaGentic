from __future__ import annotations
from .base_mgr import BaseMgr
from ..fs.write import dump_markdown

class RequestMgr(BaseMgr):
    def create(self, id_: str, label: str, summary: str, state: str = 'captured'):
        path = self.path_for('request', id_, label)
        data = {
            'id': id_,
            'label': label,
            'state': state,
            'summary': summary,
            'source_refs': [],
            'current_understanding': '',
            'open_questions': [],
        }
        body = '# Notes\n\n'
        dump_markdown(path, data, body)
        return path
