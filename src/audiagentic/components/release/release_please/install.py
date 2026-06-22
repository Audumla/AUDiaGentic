from __future__ import annotations

import json
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.lifecycle.components import DEFAULT_VERSION

_TEMPLATES = Path(__file__).parent / "templates"

SUPPORTED_RELEASE_TYPES = ["python", "node", "java", "go", "rust", "simple"]


def _render(template_name: str, subs: dict[str, str]) -> str:
    text = (_TEMPLATES / template_name).read_text(encoding="utf-8")
    for key, value in subs.items():
        text = text.replace(key, value)
    return text


def install(
    project_root: Path,
    release_type: str = "python",
    branch: str = "main",
    python_version: str = "3.13",
    initial_version: str = DEFAULT_VERSION,
) -> dict[str, list[str]]:
    if release_type not in SUPPORTED_RELEASE_TYPES:
        raise AudiaGenticError(
            code="VAL-RELINST-001",
            kind="release",
            message="unsupported release type",
            details={
                "release-type": release_type,
                "supported-release-types": list(SUPPORTED_RELEASE_TYPES),
            },
        )

    subs = {
        "__RELEASE_TYPE__": release_type,
        "__BRANCH__": branch,
        "__PYTHON_VERSION__": python_version,
    }
    files = {
        project_root / "release-please-config.json": _render("release-please-config.json", subs),
        project_root / ".release-please-manifest.json": json.dumps({".": initial_version}, indent=2) + "\n",
        project_root / ".github" / "workflows" / "release.yml": _render("release.yml", subs),
    }

    created, skipped = [], []
    for path, content in files.items():
        if path.exists():
            skipped.append(str(path.relative_to(project_root)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            created.append(str(path.relative_to(project_root)))
    return {"created": created, "skipped": skipped}
