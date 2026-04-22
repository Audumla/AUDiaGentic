from __future__ import annotations

# Legacy fallback aliases. Primary source of truth now lives in
# `.audiagentic/planning/config/planning.yaml` under `planning.kind_aliases`.
KIND_MAP = {
    'request': 'request', 'req': 'request',
    'specification': 'spec', 'spec': 'spec', 'sp': 'spec',
    'plan': 'plan', 'pl': 'plan',
    'task': 'task', 'ta': 'task',
    'work-package': 'wp', 'work_package': 'wp', 'wp': 'wp',
    'standard': 'standard',
}
