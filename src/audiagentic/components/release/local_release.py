"""Local release — build artifacts without GitHub CI/CD.

Provides build_release_artifacts() which performs the full release
pipeline locally: ledger archival, doc rendering, wheel/sdist build,
and optional tagging/publishing.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from audiagentic.components.release.release_please.finalize import render_release_docs
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.foundation.logging.redaction import redact_text

logger = logging.getLogger(__name__)

_RELEASES_DIR = ("docs", "releases")


def _get_current_version(project_root: Path) -> str:
    """Read the current version from .release-please-manifest.json."""
    manifest_path = project_root / ".release-please-manifest.json"
    if not manifest_path.exists():
        raise make_error(
            prefix="VAL", component="release", number=10,
            kind="release",
            message=".release-please-manifest.json not found — run install_release_please first",
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version = manifest.get(".")
        if not version:
            raise make_error(
                prefix="VAL", component="release", number=11,
                kind="release",
                message="No version in .release-please-manifest.json",
            )
        return version
    except AudiaGenticError:
        raise
    except Exception as exc:
        raise make_error(
            prefix="INT", component="release", number=12,
            kind="release",
            message=f"Failed to read version manifest: {exc}",
        )


def _archive_ledger_locally(project_root: Path, release_id: str) -> dict[str, Any]:
    """Archive the current ledger to LEDGER.ndjson for this release.

    This mirrors the event-driven ledger archival but runs synchronously
    without requiring the ledger component's event bus.
    """
    from audiagentic.foundation.io import atomic_write_text, load_ndjson

    releases_dir = project_root / "docs" / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)

    current_ledger_path = releases_dir / "CURRENT_RELEASE_LEDGER.ndjson"
    historical_path = releases_dir / "LEDGER.ndjson"

    if not current_ledger_path.exists():
        raise make_error(
            prefix="VAL", component="release", number=13,
            kind="release",
            message="CURRENT_RELEASE_LEDGER.ndjson not found — sync the ledger first",
        )

    events = load_ndjson(current_ledger_path)

    # Archive: move current to historical (append if historical exists)
    if historical_path.exists():
        existing = load_ndjson(historical_path)
        all_events = existing + events
    else:
        all_events = events

    atomic_write_text(historical_path, "\n".join(json.dumps(e) for e in all_events) + "\n")

    # Clear current ledger
    atomic_write_text(current_ledger_path, "[]\n")

    return {
        "release-id": release_id,
        "archived-events": len(events),
        "ledger": str(historical_path.relative_to(project_root)),
        "cleared-current": True,
    }


def build_release_artifacts(
    project_root: Path | None = None,
    release_id: str = "rel_0003",
    tag: bool = True,
    pypi: bool = False,
    github_release: bool = False,
    interactive: bool = True,
) -> dict[str, Any]:
    """Build release artifacts locally without GitHub CI/CD.

    Performs the full release pipeline:
    1. Archive ledger to LEDGER.ndjson
    2. Render CHANGELOG.md, RELEASE_NOTES.md, VERSION_HISTORY.md
    3. Build wheel and sdist via python -m build
    4. Optionally create git tag
    5. Optionally publish to PyPI
    6. Optionally create GitHub Release with artifacts

    Args:
        project_root: Project root path (defaults to cwd).
        release_id: Release identifier (e.g. rel_0003).
        tag: Whether to create a git tag.
        pypi: Whether to publish to PyPI (requires TWINE_API_TOKEN env var).
        github_release: Whether to create a GitHub Release with uploaded artifacts.
        interactive: Whether to prompt for confirmation and open browser for auth.

    Returns:
        Dict with release-id, built artifacts, tag info, and publish status.
    """
    if project_root is None:
        project_root = Path.cwd()

    project_root = project_root.resolve()

    version = _get_current_version(project_root)
    tag_name = f"v{version}"

    result: dict[str, Any] = {"release-id": release_id, "version": version, "tag-name": tag_name}

    # Step 1: Archive ledger
    logger.info("Archiving ledger for %s (version %s)", release_id, version)
    archive_result = _archive_ledger_locally(project_root, release_id)
    result["archive"] = archive_result

    # Step 2: Render release docs
    logger.info("Rendering release documents")
    docs_result = render_release_docs(project_root, release_id, released_event_ids=None)
    result["docs"] = docs_result

    # Step 3: Build wheel and sdist
    logger.info("Building wheel and sdist")
    build_result = _run_build(project_root)
    result["build"] = build_result

    # Step 4: Create git tag
    if tag:
        logger.info("Creating git tag %s", tag_name)
        tag_result = _create_git_tag(project_root, tag_name, release_id)
        result["tag"] = tag_result

    # Step 5: Publish to PyPI
    if pypi:
        logger.info("Publishing to PyPI")
        pypi_result = _publish_pypi(project_root, interactive)
        result["pypi"] = pypi_result

    # Step 6: Create GitHub Release
    if github_release:
        logger.info("Creating GitHub Release")
        gh_result = _create_github_release(project_root, tag_name, interactive)
        result["github-release"] = gh_result

    return result


def _run_build(project_root: Path) -> dict[str, Any]:
    """Run python -m build and return dist paths."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "build"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise make_error(
                prefix="INT", component="release", number=14,
                kind="release",
                message=f"Build failed (exit {proc.returncode}): {redact_text(proc.stderr)}",
            )
    except FileNotFoundError:
        raise make_error(
            prefix="VAL", component="release", number=15,
            kind="release",
            message="python -m build requires the 'build' package — pip install build",
        )
    except subprocess.TimeoutExpired:
        raise make_error(
            prefix="INT", component="release", number=16,
            kind="release",
            message="Build timed out after 300 seconds",
        )

    dist_dir = project_root / "dist"
    artifacts = []
    if dist_dir.exists():
        for f in dist_dir.iterdir():
            if f.is_file():
                artifacts.append(str(f.relative_to(project_root)))

    return {
        "success": True,
        "artifacts": artifacts,
        "dist-dir": str(dist_dir.relative_to(project_root)),
    }


def _create_git_tag(project_root: Path, tag_name: str, release_id: str) -> dict[str, Any]:
    """Create and push a git tag for this release."""
    try:
        # Create tag
        subprocess.run(
            ["git", "tag", "-a", tag_name, "-m", f"Release {release_id} ({tag_name})"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
        # Push tag
        subprocess.run(
            ["git", "push", "origin", tag_name],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return {
            "created": True,
            "tag": tag_name,
            "pushed": True,
        }
    except subprocess.CalledProcessError as exc:
        logger.warning("Git tag failed: %s", redact_text(exc.stderr))
        return {
            "created": False,
            "tag": tag_name,
            "error": redact_text(exc.stderr),
        }
    except FileNotFoundError:
        return {
            "created": False,
            "tag": tag_name,
            "error": "git not found",
        }


def _publish_pypi(project_root: Path, interactive: bool = True) -> dict[str, Any]:
    """Publish dist artifacts to PyPI via twine."""
    pypi_token = None
    for env_var in ["PYPI_API_TOKEN", "TWINE_PASSWORD"]:
        pypi_token = os.environ.get(env_var)
        if pypi_token:
            break

    if not pypi_token:
        if interactive:
            pypi_token = input("Enter PyPI API token (TWINE_PASSWORD): ")
        if not pypi_token:
            return {"published": False, "reason": "no token provided"}

    dist_dir = project_root / "dist"
    if not dist_dir.exists():
        return {"published": False, "reason": "dist/ directory not found"}

    files = [str(f) for f in dist_dir.iterdir() if f.is_file()]
    if not files:
        return {"published": False, "reason": "no files in dist/"}

    try:
        proc = subprocess.run(
            ["twine", "upload", "--non-interactive"] + files,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "TWINE_PASSWORD": pypi_token},
        )
        if proc.returncode != 0:
            return {
                "published": False,
                "error": redact_text(proc.stderr),
            }
        return {
            "published": True,
            "files": [str(Path(f).name) for f in files],
        }
    except FileNotFoundError:
        return {
            "published": False,
            "reason": "twine not found — pip install twine",
        }
    except subprocess.TimeoutExpired:
        return {
            "published": False,
            "reason": "publish timed out after 300 seconds",
        }


def _create_github_release(
    project_root: Path, tag_name: str, interactive: bool = True
) -> dict[str, Any]:
    """Create a GitHub Release with uploaded artifacts using gh CLI."""
    try:
        # Check if gh is available
        proc = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return {
                "created": False,
                "reason": "gh CLI not available",
            }
    except FileNotFoundError:
        return {
            "created": False,
            "reason": "gh CLI not found",
        }

    dist_dir = project_root / "dist"
    files = [str(f) for f in dist_dir.iterdir() if f.is_file()] if dist_dir.exists() else []
    if not files:
        return {
            "created": False,
            "reason": "no files in dist/ to upload",
        }

    # Build upload args for gh release upload
    upload_args = ["gh", "release", "upload", tag_name] + files

    try:
        proc = subprocess.run(
            upload_args,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            return {
                "created": False,
                "error": redact_text(proc.stderr),
            }
        return {
            "created": True,
            "tag": tag_name,
            "files": [str(Path(f).name) for f in files],
        }
    except subprocess.TimeoutExpired:
        return {
            "created": False,
            "reason": "release creation timed out after 300 seconds",
        }
