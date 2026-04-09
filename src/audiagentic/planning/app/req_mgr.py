from __future__ import annotations
from pathlib import Path
import yaml
from .base_mgr import BaseMgr
from ..fs.write import dump_markdown

class RequestMgr(BaseMgr):
    def _load_request_profile(self, profile: str | None) -> dict:
        if not profile:
            return {}
        path = self.root / '.audiagentic' / 'planning' / 'config' / 'request-profiles.yaml'
        if not path.exists():
            raise ValueError(f"request profile '{profile}' not found: request-profiles.yaml is missing")
        cfg = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        data = cfg.get('request_profiles', {}).get(profile)
        if data is None:
            raise ValueError(f"request profile '{profile}' does not exist")
        return data if isinstance(data, dict) else {}

    def _default_open_questions(self, profile: str | None) -> list[str]:
        if profile == 'issue':
            return [
                'What is the observed impact or failure mode?',
                'How can this be reproduced or verified?',
                'What constraints or non-goals apply?',
            ]
        if profile == 'feature':
            return [
                'What exact outcome is required?',
                'What constraints or non-goals apply?',
                'How will success be verified?',
            ]
        return [
            'What exact outcome is required?',
            'What constraints or non-goals apply?',
            'What follow-up detail is still needed before implementation?',
        ]

    def _default_understanding(self, summary: str, profile: str | None) -> str:
        if profile == 'issue':
            return f"Initial issue intake captured: {summary}"
        if profile == 'feature':
            return f"Initial feature intake captured: {summary}"
        return f"Initial request intake captured: {summary}"

    def _build_body(
        self,
        understanding: str,
        open_questions: list[str],
        source_refs: list[str],
        suggested_sections: list[str],
    ) -> str:
        sections: list[str] = [
            '# Understanding',
            '',
            understanding,
            '',
            '# Source Refs',
            '',
        ]
        if source_refs:
            sections.extend(f'- {ref}' for ref in source_refs)
        else:
            sections.append('- Add links, file paths, issue ids, or planning refs here.')
        sections.extend(['', '# Open Questions', ''])
        if open_questions:
            sections.extend(f'- {question}' for question in open_questions)
        else:
            sections.append('- Add open questions here.')
        for section in suggested_sections:
            sections.extend(['', f'# {section}', '', ''])
        sections.extend(['# Notes', '', ''])
        return '\n'.join(sections)

    def create(
        self,
        id_: str,
        label: str,
        summary: str,
        state: str = 'captured',
        profile: str | None = None,
        source_refs: list[str] | None = None,
        current_understanding: str | None = None,
        open_questions: list[str] | None = None,
    ):
        path = self.path_for('request', id_, label)
        profile_cfg = self._load_request_profile(profile)
        defaults = profile_cfg.get('defaults', {}) if isinstance(profile_cfg, dict) else {}
        default_meta = defaults.get('meta', {}) if isinstance(defaults.get('meta', {}), dict) else {}
        default_source_refs = defaults.get('source_refs') if isinstance(defaults.get('source_refs'), list) else []
        default_understanding = defaults.get('current_understanding') if isinstance(defaults.get('current_understanding'), str) else None
        default_open_questions = defaults.get('open_questions') if isinstance(defaults.get('open_questions'), list) else []
        source_refs = source_refs if source_refs is not None else default_source_refs
        current_understanding = current_understanding or default_understanding or self._default_understanding(summary, profile)
        open_questions = open_questions if open_questions is not None else (default_open_questions or self._default_open_questions(profile))
        data = {
            'id': id_,
            'label': label,
            'state': state,
            'summary': summary,
            'source_refs': source_refs,
            'current_understanding': current_understanding,
            'open_questions': open_questions,
        }
        if default_meta:
            data['meta'] = default_meta
        suggested_sections = profile_cfg.get('suggested_sections', []) if isinstance(profile_cfg, dict) else []
        body = self._build_body(current_understanding, open_questions, source_refs, suggested_sections)
        dump_markdown(path, data, body)
        return path
