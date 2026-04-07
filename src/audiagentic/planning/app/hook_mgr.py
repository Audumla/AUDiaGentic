from __future__ import annotations

import logging
import re
from pathlib import Path

from .config import Config
from .events import EventLog

_logger = logging.getLogger(__name__)

# AUDiaGentic target grammar patterns for normalization
_PKT_PATTERN = re.compile(r'^[A-Z]+-[A-Z]+-\d+$', re.IGNORECASE)
_JOB_PATTERN = re.compile(r'^job_\d{8}_\d+$')
_ALREADY_FORMATTED = re.compile(r'^(packet:|job:|artifact:|adhoc)')


def normalize_target(raw: str | None) -> str:
    """Normalize a planning task target string to AUDiaGentic target grammar.

    Accepts:
        - ``PKT-PRV-061``          → ``packet:PKT-PRV-061``
        - ``packet:PKT-PRV-061``   → unchanged
        - ``job:job_20240407_001`` → unchanged
        - ``adhoc``                → unchanged
        - ``None`` / empty         → ``adhoc``

    Used by the dispatch_job hook stub at dispatch time.
    """
    if not raw:
        return "adhoc"
    raw = raw.strip()
    if not raw:
        return "adhoc"
    if _ALREADY_FORMATTED.match(raw):
        return raw
    if _PKT_PATTERN.match(raw):
        return f"packet:{raw.upper()}"
    if _JOB_PATTERN.match(raw):
        return f"job:{raw}"
    # Unrecognised — pass through; the execution engine will reject if invalid
    return raw


class Hooks:
    def __init__(self, root: Path, api_getter=None):
        self.root = root
        self.config = Config(root)
        self.event_log = EventLog(root / '.audiagentic/planning/events/events.jsonl')
        self.api_getter = api_getter

    def run(self, phase: str, kind: str, payload: dict):
        hooks = self.config.hooks.get('planning', {}).get('hooks', {})
        actions = []
        actions.extend(hooks.get(phase, {}).get(kind, []) or [])
        actions.extend(hooks.get(phase, {}).get('planning', []) or [])
        for act in actions:
            self.apply(act['action'], kind, phase, payload, act.get('params', {}))

    def apply(self, action: str, kind: str, phase: str, payload: dict, params: dict):
        if action == 'emit_event':
            self.event_log.emit(f'{kind}.{phase}', payload)
        elif action == 'index' and self.api_getter:
            self.api_getter().index()
        elif action == 'validate' and self.api_getter:
            self.api_getter().validate(raise_on_error=True)
        elif action == 'review_stub':
            self.event_log.emit(f'{kind}.review_stub', payload)
        elif action == 'report_stub':
            self.event_log.emit(f'{kind}.report_stub', payload)
        elif action == 'note_stub':
            self.event_log.emit(f'{kind}.note_stub', {'note': params.get('note'), **payload})
        elif action == 'dispatch_job':
            self._dispatch_job_stub(kind, phase, payload, params)
        else:
            _logger.debug("planning hook: unknown action %r (kind=%s phase=%s)", action, kind, phase)

    def _dispatch_job_stub(self, kind: str, phase: str, payload: dict, params: dict) -> None:
        """Stub: dispatch an AUDiaGentic job for a planning task or work-package.

        Phase 2 wiring (when job-completion hooks are ready):
            from audiagentic.execution.jobs.prompt_launch import launch_prompt_request
            result = launch_prompt_request(self.root, request)
            job_id = result.get("job-id")
            # then write job_id to dispatch registry below

        Currently: normalizes target, records intent in dispatch registry and event log.
        """
        item_id = payload.get('id', '<unknown>')
        raw_target = payload.get('target') or payload.get('packet_ref')
        normalized = normalize_target(raw_target)
        _logger.info(
            "planning dispatch_job stub: kind=%s id=%s target=%s normalized=%s",
            kind, item_id, raw_target, normalized,
        )
        self.event_log.emit(
            f'{kind}.dispatch_job_stub',
            {
                'id': item_id,
                'raw_target': raw_target,
                'normalized_target': normalized,
                'provider': params.get('provider'),
                'workflow_profile': params.get('workflow_profile', 'standard'),
            },
        )
        # Record intent in dispatch registry (job-id will be populated in Phase 2)
        _update_dispatch_registry(self.root, planning_id=item_id, kind=kind, job_id=None)


def _update_dispatch_registry(root: Path, *, planning_id: str, kind: str, job_id: str | None) -> None:
    """Add or update an entry in .audiagentic/planning/indexes/dispatch.json.

    Schema: {"entries": [{"planning-id": str, "kind": str, "job-ids": [str], "updated-at": str}]}
    """
    import json
    from .util import now_iso

    reg_path = root / ".audiagentic" / "planning" / "indexes" / "dispatch.json"
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    if reg_path.exists():
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
    else:
        registry = {"entries": []}

    entries = registry.setdefault("entries", [])
    entry = next((e for e in entries if e["planning-id"] == planning_id), None)
    if entry is None:
        entry = {"planning-id": planning_id, "kind": kind, "job-ids": [], "updated-at": now_iso()}
        entries.append(entry)
    if job_id and job_id not in entry["job-ids"]:
        entry["job-ids"].append(job_id)
    entry["updated-at"] = now_iso()
    reg_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
