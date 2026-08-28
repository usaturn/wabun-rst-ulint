"""fileset モジュールのテスト。"""

import logging
from pathlib import Path

import pytest

from wabun_rst_ulint.fileset import (
    collect_rst_files,
    collect_rst_files_pruned,
)

logger = logging.getLogger("test_fileset")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "sub").mkdir(parents=True)
    (tmp_path / "docs" / "a.rst").write_text("a\n", encoding="utf-8")
    (tmp_path / "docs" / "sub" / "b.rst").write_text("b\n", encoding="utf-8")
    (tmp_path / "docs" / "c.txt").write_text("c\n", encoding="utf-8")
    (tmp_path / "docs" / ".venv").mkdir()
    (tmp_path / "docs" / ".venv" / "x.rst").write_text("x\n", encoding="utf-8")
    return tmp_path


def test_collect_dir_recursive_sorted(tree: Path):
    result = collect_rst_files([tree / "docs"], logger.warning)
    # 除外ディレクトリの概念がないため .venv 配下も含む（元の spacing 系の挙動）
    assert result == sorted((tree / "docs").rglob("*.rst"))


def test_collect_file_non_rst_skipped_with_warning(tree: Path, caplog):
    with caplog.at_level(logging.WARNING, logger="test_fileset"):
        result = collect_rst_files([tree / "docs" / "c.txt"], logger.warning)
    assert result == []
    assert "（.rst ファイルではありません）" in caplog.text


def test_collect_missing_path_skipped_with_warning(tree: Path, caplog):
    with caplog.at_level(logging.WARNING, logger="test_fileset"):
        result = collect_rst_files([tree / "nope"], logger.warning)
    assert result == []
    assert "（存在しません）" in caplog.text


def test_pruned_excludes_managed_dirs(tree: Path):
    result = collect_rst_files_pruned([tree / "docs"], follow_symlinks=False, logger=logger)
    names = [p.name for p in result]
    assert names == ["a.rst", "b.rst"]


def test_pruned_explicit_excluded_dir_is_respected(tree: Path):
    # ユーザが .venv を直接指定した場合は除外しない
    result = collect_rst_files_pruned([tree / "docs" / ".venv"], follow_symlinks=False, logger=logger)
    assert [p.name for p in result] == ["x.rst"]


def test_pruned_symlink_skipped_by_default(tree: Path, caplog):
    link = tree / "docs" / "link.rst"
    link.symlink_to(tree / "docs" / "a.rst")
    with caplog.at_level(logging.WARNING, logger="test_fileset"):
        result = collect_rst_files_pruned([link], follow_symlinks=False, logger=logger)
    assert result == []
    assert "--follow-symlinks" in caplog.text
    assert collect_rst_files_pruned([link], follow_symlinks=True, logger=logger) == [link]


def test_collect_deduplicates_overlapping_args(tree: Path):
    # ディレクトリと配下ファイルを重ねて指定しても 1 回だけ収集する
    result = collect_rst_files([tree / "docs", tree / "docs" / "a.rst"], logger.warning)
    assert result.count(tree / "docs" / "a.rst") == 1


def test_pruned_deduplicates_overlapping_args(tree: Path):
    result = collect_rst_files_pruned([tree / "docs", tree / "docs"], follow_symlinks=False, logger=logger)
    assert [p.name for p in result] == ["a.rst", "b.rst"]


def test_collect_deduplicates_relative_and_absolute(tree: Path, monkeypatch):
    monkeypatch.chdir(tree)
    rel = Path("docs") / "a.rst"
    abso = tree / "docs" / "a.rst"
    result = collect_rst_files([rel, abso], logger.warning)
    resolved = [p.resolve() for p in result]
    assert len(resolved) == len(set(resolved))


def test_expand_paths_removed():
    """Issue #14: 削除済みチェッカー専用の収集バリアントは残さない。"""
    import wabun_rst_ulint.fileset as fileset

    assert not hasattr(fileset, "expand_paths")
