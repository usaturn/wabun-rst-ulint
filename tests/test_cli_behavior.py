"""最終 4 コマンドの振る舞い表（走査・重複除去・警告・終了コード）の結合テスト。

チェッカーは実物を動かし、実際の一時ファイルを対象にする。
モックは I/O エラーの強制のみに限定する。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from wabun_rst_ulint.cli import main

ALL_COMMANDS = ["inline-spacing", "strong-spacing", "heading-width", "sentence-breaks"]


# ---------------------------------------------------------------------------
# 走査差: spacing 系は非 prune、heading-width / sentence-breaks は prune
# ---------------------------------------------------------------------------


def test_inline_spacing_does_not_prune_managed_directories(tmp_path: Path, capsys):
    hidden = tmp_path / ".venv"
    hidden.mkdir()
    (hidden / "x.rst").write_text("値は``foo``です\n", encoding="utf-8")
    assert main(["inline-spacing", str(tmp_path)]) == 1
    assert "x.rst" in capsys.readouterr().err


def test_strong_spacing_does_not_prune_managed_directories(tmp_path: Path, capsys):
    hidden = tmp_path / ".venv"
    hidden.mkdir()
    (hidden / "x.rst").write_text("本文**重要**です\n", encoding="utf-8")
    assert main(["strong-spacing", str(tmp_path)]) == 1
    assert "x.rst" in capsys.readouterr().err


def test_sentence_breaks_prunes_managed_directories(tmp_path: Path, capsys):
    hidden = tmp_path / ".venv"
    hidden.mkdir()
    (hidden / "x.rst").write_text("一文目。二文目\n", encoding="utf-8")
    assert main(["sentence-breaks", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "[Rule1]" not in captured.out
    assert "エラー: .rst ファイルが見つかりませんでした" in captured.err


def test_heading_width_prunes_managed_directories(tmp_path: Path, caplog):
    hidden = tmp_path / ".venv"
    hidden.mkdir()
    (hidden / "x.rst").write_text("見出し\n====\n", encoding="utf-8")
    with caplog.at_level(logging.INFO):
        assert main(["heading-width", str(tmp_path)]) == 1
    assert "エラー: .rst ファイルが見つかりませんでした" in caplog.text


# ---------------------------------------------------------------------------
# 対象ゼロ・非 .rst・不在パス
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_no_target_exits_1(command: str, tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main([command, str(empty)]) == 1


def test_spacing_warns_and_skips_non_rst_path(tmp_path: Path, capsys):
    other = tmp_path / "a.txt"
    other.write_text("値は``foo``です\n", encoding="utf-8")
    assert main(["inline-spacing", str(other)]) == 1
    err = capsys.readouterr().err
    assert "スキップ" in err
    assert "a.txt" in err
    assert "検査対象の .rst ファイルがない" in err


def test_spacing_warns_and_skips_missing_path(tmp_path: Path, capsys):
    assert main(["strong-spacing", str(tmp_path / "nope.rst")]) == 1
    err = capsys.readouterr().err
    assert "存在しません" in err
    assert "検査対象の .rst ファイルがない" in err


def test_sentence_breaks_warns_and_skips_non_rst_path(tmp_path: Path, caplog):
    other = tmp_path / "a.txt"
    other.write_text("一文目。二文目\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert main(["sentence-breaks", str(other)]) == 1
    assert ".rst ファイルではありません" in caplog.text


def test_heading_width_warns_and_skips_missing_path(tmp_path: Path, caplog):
    with caplog.at_level(logging.WARNING):
        assert main(["heading-width", str(tmp_path / "nope.rst")]) == 1
    assert "存在しません" in caplog.text


# ---------------------------------------------------------------------------
# 初出順の重複除去（ディレクトリ + 配下ファイルの二重指定）
# ---------------------------------------------------------------------------


def test_inline_spacing_deduplicates_paths(tmp_path: Path, capsys):
    target = tmp_path / "a.rst"
    target.write_text("値は``foo``です\n", encoding="utf-8")
    assert main(["inline-spacing", str(tmp_path), str(target)]) == 1
    assert capsys.readouterr().err.count("literal の外部境界空白が不正") == 1


def test_strong_spacing_deduplicates_paths(tmp_path: Path, capsys):
    target = tmp_path / "a.rst"
    target.write_text("本文**重要**です\n", encoding="utf-8")
    assert main(["strong-spacing", str(tmp_path), str(target)]) == 1
    # 1 ファイルにつき「前」「後」の 2 件。重複処理されると 4 件になる
    assert capsys.readouterr().err.count("strong の外部境界に半角スペースが必要") == 2


def test_sentence_breaks_deduplicates_paths(tmp_path: Path, capsys):
    target = tmp_path / "a.rst"
    target.write_text("一文目。二文目\n", encoding="utf-8")
    assert main(["sentence-breaks", str(tmp_path), str(target)]) == 1
    assert capsys.readouterr().out.count("[Rule1]") == 1


def test_heading_width_deduplicates_paths(tmp_path: Path, caplog):
    target = tmp_path / "a.rst"
    target.write_text("見出し\n====\n", encoding="utf-8")
    with caplog.at_level(logging.INFO):
        assert main(["heading-width", str(tmp_path), str(target)]) == 1
    assert "検出結果: 1 件の違反が見つかりました" in caplog.text


# ---------------------------------------------------------------------------
# check 違反で 1 / fix 成功で 0
# ---------------------------------------------------------------------------


def test_inline_spacing_check_then_fix(tmp_path: Path):
    target = tmp_path / "a.rst"
    target.write_text("値は``foo``です\n", encoding="utf-8")
    assert main(["inline-spacing", str(target)]) == 1
    assert target.read_text(encoding="utf-8") == "値は``foo``です\n"
    assert main(["inline-spacing", "--fix", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == "値は ``foo`` です\n"


def test_strong_spacing_check_then_fix(tmp_path: Path):
    target = tmp_path / "a.rst"
    target.write_text("本文**重要**です\n", encoding="utf-8")
    assert main(["strong-spacing", "--check", str(target)]) == 1
    assert target.read_text(encoding="utf-8") == "本文**重要**です\n"
    assert main(["strong-spacing", "--fix", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == "本文 **重要** です\n"


def test_heading_width_check_then_fix(tmp_path: Path):
    target = tmp_path / "a.rst"
    target.write_text("見出し\n====\n", encoding="utf-8")
    assert main(["heading-width", str(target)]) == 1
    assert target.read_text(encoding="utf-8") == "見出し\n====\n"
    assert main(["heading-width", "--fix", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == "見出し\n======\n"


def test_sentence_breaks_check_then_fix(tmp_path: Path):
    target = tmp_path / "a.rst"
    target.write_text("一文目。二文目\n", encoding="utf-8")
    assert main(["sentence-breaks", str(target)]) == 1
    assert target.read_text(encoding="utf-8") == "一文目。二文目\n"
    assert main(["sentence-breaks", "--fix", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == "一文目。\n二文目\n"


# ---------------------------------------------------------------------------
# シンボリックリンク
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["inline-spacing", "strong-spacing"])
def test_spacing_commands_have_no_follow_symlinks_option(command: str, tmp_path: Path):
    target = tmp_path / "a.rst"
    target.write_text("本文\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main([command, "--follow-symlinks", str(target)])
    assert excinfo.value.code == 2


def test_inline_spacing_inspects_symlinked_rst_without_flag(tmp_path: Path, capsys):
    real = tmp_path / "real.rst"
    real.write_text("値は``foo``です\n", encoding="utf-8")
    link = tmp_path / "link.rst"
    link.symlink_to(real)
    assert main(["inline-spacing", str(link)]) == 1
    assert "link.rst" in capsys.readouterr().err


def test_sentence_breaks_skips_symlink_unless_flagged(tmp_path: Path, caplog, capsys):
    real = tmp_path / "real.rst"
    real.write_text("一文目。二文目\n", encoding="utf-8")
    link = tmp_path / "link.rst"
    link.symlink_to(real)

    with caplog.at_level(logging.WARNING):
        assert main(["sentence-breaks", str(link)]) == 1
    assert "シンボリックリンクです" in caplog.text
    assert "[Rule1]" not in capsys.readouterr().out

    assert main(["sentence-breaks", "--follow-symlinks", str(link)]) == 1
    assert "[Rule1]" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# コマンド別 I/O 終了コード（sentence-breaks のみ 2）
# ---------------------------------------------------------------------------


@pytest.fixture
def force_read_error(monkeypatch):
    """指定名のファイルだけ読み込みを OSError にする（他ファイルは実 I/O のまま）。"""

    def install(name: str) -> None:
        real_read_text = Path.read_text
        real_open = Path.open

        def failing_read_text(self, *args, **kwargs):
            if self.name == name:
                raise OSError("Permission denied")
            return real_read_text(self, *args, **kwargs)

        def failing_open(self, *args, **kwargs):
            if self.name == name:
                raise OSError("Permission denied")
            return real_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", failing_read_text)
        monkeypatch.setattr(Path, "open", failing_open)

    return install


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("inline-spacing", 1),
        ("strong-spacing", 1),
        ("heading-width", 1),
        ("sentence-breaks", 2),
    ],
)
def test_io_error_exit_codes(command: str, expected: int, tmp_path: Path, force_read_error):
    target = tmp_path / "nope.rst"
    target.write_text("見出し\n====\n", encoding="utf-8")
    force_read_error("nope.rst")
    assert main([command, str(target)]) == expected
