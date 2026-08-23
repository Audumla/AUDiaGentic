from __future__ import annotations

from pathlib import Path

from dulwich import porcelain, worktree
from dulwich.repo import Repo

from audiagentic.components.source_control import source_control_api


def _commit_repository(root: Path, *, branch: bytes = b"main") -> Repo:
    root.mkdir()
    repository = Repo.init(str(root))
    (root / "README.md").write_text("source-control context\n", encoding="utf-8")
    porcelain.add(repository, paths=["README.md"])
    porcelain.commit(
        repository,
        message=b"initial",
        author=b"AUDiaGentic <tests@example.invalid>",
        committer=b"AUDiaGentic <tests@example.invalid>",
    )
    head = repository.head()
    repository.refs[b"refs/heads/" + branch] = head
    repository.refs.set_symbolic_ref(b"HEAD", b"refs/heads/" + branch)
    return repository


def test_context_reads_normal_repository_from_nested_directory(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    repository = _commit_repository(root, branch=b"feature/context")
    repository.close()
    nested = root / "nested" / "directory"
    nested.mkdir(parents=True)

    result = source_control_api.context(nested)

    assert result["repository"] is None
    assert result["repository_name"] == "repository"
    assert result["root"] == str(root.resolve())
    assert result["branch"] == "feature/context"
    assert result["commit"]
    assert result["commit_short"] == result["commit"][:12]
    assert result["detached"] is False


def test_context_handles_detached_head(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    repository = _commit_repository(root)
    head = repository.head()
    del repository.refs[b"HEAD"]
    repository.refs[b"HEAD"] = head
    repository.close()

    result = source_control_api.context(root)

    assert result["root"] == str(root.resolve())
    assert result["branch"] is None
    assert result["commit"] == head.decode("ascii")
    assert result["detached"] is True


def test_context_handles_unborn_repository(tmp_path: Path) -> None:
    root = tmp_path / "unborn"
    root.mkdir()
    repository = Repo.init(str(root))
    repository.close()

    result = source_control_api.context(root)

    assert result == {
        "repository": None,
        "repository_name": "unborn",
        "root": str(root.resolve()),
        "branch": None,
        "commit": None,
        "commit_short": None,
        "detached": False,
    }


def test_context_reads_packed_branch_ref(tmp_path: Path) -> None:
    root = tmp_path / "packed"
    repository = _commit_repository(root, branch=b"packed-branch")
    repository.refs.pack_refs()
    repository.close()

    result = source_control_api.context(root)

    assert result["branch"] == "packed-branch"
    assert result["commit"]


def test_context_uses_linked_worktree_root_and_branch(tmp_path: Path) -> None:
    root = tmp_path / "main-worktree"
    repository = _commit_repository(root, branch=b"main")
    head = repository.head()
    repository.refs[b"refs/heads/linked"] = head
    linked = tmp_path / "linked-worktree"
    linked_repository = worktree.add_worktree(repository, linked, branch=b"linked")
    linked_repository.close()
    repository.close()

    result = source_control_api.context(linked)

    assert result["repository"] is None
    assert result["repository_name"] == "linked-worktree"
    assert result["root"] == str(linked.resolve())
    assert result["branch"] == "linked"
    assert result["commit"] == head.decode("ascii")


def test_context_returns_safe_null_for_non_repository(tmp_path: Path) -> None:
    path = tmp_path / "not-a-repository"
    path.mkdir()

    assert source_control_api.context(path) == {
        "repository": None,
        "repository_name": "not-a-repository",
        "root": None,
        "branch": None,
        "commit": None,
        "commit_short": None,
        "detached": False,
    }


def test_context_returns_safe_null_for_corrupt_repository_metadata(tmp_path: Path) -> None:
    root = tmp_path / "corrupt"
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("not a valid ref\n", encoding="utf-8")

    assert source_control_api.context(root) == {
        "repository": None,
        "repository_name": "corrupt",
        "root": None,
        "branch": None,
        "commit": None,
        "commit_short": None,
        "detached": False,
    }


def test_context_has_no_subprocess_dependency() -> None:
    source = Path(source_control_api.__file__).read_text(encoding="utf-8")

    assert "subprocess" not in source
    assert "_git_value" not in source
