"""Project identity facts that do not need the settings: a path-safe name and the git repository's.

Shared by the settings resolver (which names the user-project scope file) and the project component
(which reports identity). Reads git's own files rather than running git.
"""
from __future__ import annotations

import re
from pathlib import Path


def path_safe_id(name: str) -> str | None:
    """Restrict a name to the ``project.id`` schema: [A-Za-z0-9._-], alnum first, 64 chars."""
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).lstrip("._-")[:64].rstrip("._-")
    return candidate or None


def strip_git_suffix(name: str) -> str:
    return name[: -len(".git")] if name.endswith(".git") else name


def repository_name(url: str) -> str:
    return strip_git_suffix(url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])


def git_common_dir(project_root: Path) -> Path | None:
    """The git common directory of project_root (shared by all its worktrees).

    Reads git's own files rather than running git, so it is cheap and has no
    process or PATH dependency. Any unreadable layout yields None.
    """
    try:
        dot_git = project_root.resolve() / ".git"
        if dot_git.is_dir():
            git_dir = dot_git
        elif dot_git.is_file():
            pointer = dot_git.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            git_dir = (project_root.resolve() / pointer[len("gitdir:"):].strip()).resolve()
        else:
            return None
        commondir = git_dir / "commondir"
        return (git_dir / commondir.read_text(encoding="utf-8").strip()).resolve() if commondir.is_file() else git_dir
    except OSError:
        return None


def git_repository_identity(project_root: Path) -> tuple[str, str] | None:
    """Name the git repository at project_root: origin's repo, else main checkout."""
    common = git_common_dir(project_root)
    if common is None:
        return None
    try:
        origin = remote_urls(common / "config").get("origin")
    except OSError:
        return None
    name = repository_name(origin) if origin else ""
    source = "git-remote"
    if not name:
        name, source = strip_git_suffix(common.parent.name if common.name == ".git" else common.name), "main-checkout"
    return (name.strip(), source) if name.strip() else None


def remote_urls(config_path: Path) -> dict[str, str]:
    """``url`` of each ``[remote "name"]`` section in a git config file."""
    if not config_path.is_file():
        return {}
    urls: dict[str, str] = {}
    remote = None
    for raw in config_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("["):
            section = line.strip("[]").strip()
            remote = section[len("remote"):].strip().strip('"') if section.startswith("remote ") else None
        elif remote and line.split("=", 1)[0].strip() == "url" and "=" in line:
            url = line.split("=", 1)[1].strip()
            if url:
                urls.setdefault(remote, url)
    return urls


def project_identity(project_root: Path, declared: str | None = None) -> str:
    """The path-safe project identity: ``declared`` (``project.id``), else the git repository, else the folder."""
    if declared and path_safe_id(declared) == declared:
        return declared
    found = git_repository_identity(project_root)
    name = found[0] if found else project_root.resolve().name
    return path_safe_id(name) or "project"
