from __future__ import annotations

import json
import logging
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.lifecycle.components import DEFAULT_VERSION

from . import utils

logger = logging.getLogger(__name__)

SUPPORTED_RELEASE_TYPES = ["python", "node", "java", "go", "rust", "simple"]

TEMPLATE_PLACEHOLDERS = {
    "release-please-config.json": ["__RELEASE_TYPE__"],
    "release.yml": ["__BRANCH__", "__PYTHON_VERSION__"],
    "baseline.yml": ["__BRANCH__", "__PYTHON_VERSION__"],
}


def _validate_render(template_name: str, text: str, subs: dict[str, str]) -> None:
    expected = set(TEMPLATE_PLACEHOLDERS.get(template_name, []))
    for placeholder in expected:
        if placeholder in text:
            raise make_error(
                prefix="VAL", component="release", number=2,
                kind="release",
                message=f"unreplaced placeholder in {template_name}",
                details={"placeholder": placeholder},
            )


def install(
    project_root: Path,
    release_type: str = "python",
    branch: str = "main",
    python_version: str = "3.13",
    initial_version: str = DEFAULT_VERSION,
) -> dict[str, list[str]]:
    if release_type not in SUPPORTED_RELEASE_TYPES:
        raise make_error(
            prefix="VAL", component="release", number=1,
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
    rendered_config = utils.render("release-please-config.json", subs)
    _validate_render("release-please-config.json", rendered_config, subs)
    rendered_workflow = utils.render("release.yml", subs)
    _validate_render("release.yml", rendered_workflow, subs)

    files = {
        project_root / "release-please-config.json": rendered_config,
        project_root / ".release-please-manifest.json": json.dumps({".": initial_version}, indent=2) + "\n",
        project_root / ".github" / "workflows" / "release.yml": rendered_workflow,
    }

    created, skipped = [], []
    for path, content in files.items():
        if path.exists():
            skipped.append(str(path.relative_to(project_root)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            created.append(str(path.relative_to(project_root)))

    if skipped:
        logger.warning(
            "Skipped existing release files — they may have stale content: %s",
            skipped,
        )

    return {"created": created, "skipped": skipped}
