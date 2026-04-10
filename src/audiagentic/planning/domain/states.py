from __future__ import annotations

KIND_MAP = {
    'request': 'request', 'req': 'request',
    'specification': 'spec', 'spec': 'spec', 'sp': 'spec',
    'plan': 'plan', 'pl': 'plan',
    'task': 'task', 'ta': 'task',
    'work-package': 'wp', 'work_package': 'wp', 'wp': 'wp',
    'standard': 'standard',
}

CANONICAL_KINDS = {'request', 'spec', 'plan', 'task', 'wp', 'standard'}
