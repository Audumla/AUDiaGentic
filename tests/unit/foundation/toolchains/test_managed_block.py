from __future__ import annotations

from audiagentic.foundation.toolchains.managed_block import (
    apply_managed_block,
    remove_managed_block,
)


def test_apply_appends_block_to_new_file(tmp_path):
    f = tmp_path / "rc"
    change = apply_managed_block(f, "hook", "line1\nline2")
    text = f.read_text(encoding="utf-8")
    assert ">>> audiagentic:hook >>>" in text
    assert "<<< audiagentic:hook <<<" in text
    assert "line1" in text
    assert change.existed is False


def test_reapply_replaces_in_place(tmp_path):
    f = tmp_path / "rc"
    apply_managed_block(f, "hook", "old")
    change = apply_managed_block(f, "hook", "new")
    text = f.read_text(encoding="utf-8")
    assert "old" not in text
    assert "new" in text
    assert change.existed is True
    # exactly one marker pair
    assert text.count(">>> audiagentic:hook >>>") == 1


def test_remove_strips_only_marked_region(tmp_path):
    f = tmp_path / "rc"
    f.write_text("before\n", encoding="utf-8")
    apply_managed_block(f, "hook", "managed")
    with open(f, "a", encoding="utf-8") as fh:
        fh.write("after\n")

    change = remove_managed_block(f, "hook")
    text = f.read_text(encoding="utf-8")
    assert change.existed is True
    assert "managed" not in text
    assert "before" in text
    assert "after" in text


def test_remove_absent_block_is_noop(tmp_path):
    f = tmp_path / "rc"
    f.write_text("content\n", encoding="utf-8")
    change = remove_managed_block(f, "nope")
    assert change.existed is False
    assert f.read_text(encoding="utf-8") == "content\n"


def test_two_blocks_coexist(tmp_path):
    f = tmp_path / "rc"
    apply_managed_block(f, "a", "AAA")
    apply_managed_block(f, "b", "BBB")
    remove_managed_block(f, "a")
    text = f.read_text(encoding="utf-8")
    assert "AAA" not in text
    assert "BBB" in text
