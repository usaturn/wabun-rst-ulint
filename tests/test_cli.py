"""CLI 表面（最終 4 コマンド）の契約テスト。"""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
from typing import Any

import pytest

from wabun_rst_ulint.cli import build_parser, main

FINAL_COMMANDS = ["inline-spacing", "strong-spacing", "heading-width", "sentence-breaks"]

# Issue #14 で撤去した 6 名。エイリアスも非推奨警告も残さず argparse が拒否する
REMOVED_COMMANDS = [
    "literal-spacing",
    "role-spacing",
    "role-visible-spacing",
    "section-underline",
    "inline-markup",
    "kuten",
]


@pytest.fixture
def rst(tmp_path: Path) -> Path:
    target = tmp_path / "a.rst"
    target.write_text("値は``foo``です\n", encoding="utf-8")
    return target


def _subparsers_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    return next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))


def test_program_name():
    assert build_parser().prog == "wabun-rst-ulint"


def test_exactly_four_subcommands_registered():
    assert list(_subparsers_action(build_parser()).choices) == FINAL_COMMANDS


def test_help_lists_only_final_commands(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for name in FINAL_COMMANDS:
        assert name in out, name
    for name in REMOVED_COMMANDS:
        assert name not in out, name


@pytest.mark.parametrize("command", FINAL_COMMANDS)
def test_each_final_command_has_check_and_fix(command: str):
    subparser = _subparsers_action(build_parser()).choices[command]
    options = {option for action in subparser._actions for option in action.option_strings}
    assert "--check" in options
    assert "--fix" in options


@pytest.mark.parametrize("command", REMOVED_COMMANDS)
def test_removed_command_is_rejected(command: str, rst: Path):
    with pytest.raises(SystemExit) as excinfo:
        main([command, str(rst)])
    assert excinfo.value.code == 2


def test_missing_subcommand_is_rejected():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


@pytest.mark.parametrize("command", FINAL_COMMANDS)
def test_check_and_fix_are_mutually_exclusive(command: str, rst: Path):
    with pytest.raises(SystemExit) as excinfo:
        main([command, "--check", "--fix", str(rst)])
    assert excinfo.value.code == 2


def _record_run(monkeypatch, module_name: str) -> dict[str, Any]:
    """チェッカーの run() を差し替え、CLI が渡した引数を記録する。"""
    module = importlib.import_module(f"wabun_rst_ulint.checkers.{module_name}")
    seen: dict[str, Any] = {}

    def fake_run(paths, **kwargs):
        seen["paths"] = list(paths)
        seen["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(module, "run", fake_run)
    return seen


def test_inline_spacing_dispatches_to_inline_spacing_module(monkeypatch, rst: Path):
    seen = _record_run(monkeypatch, "inline_spacing")
    assert main(["inline-spacing", "--fix", str(rst)]) == 0
    assert seen["paths"] == [rst]
    assert seen["kwargs"] == {"fix": True}


def test_strong_spacing_dispatches_to_strong_emphasis_spacing_module(monkeypatch, rst: Path):
    seen = _record_run(monkeypatch, "strong_emphasis_spacing")
    assert main(["strong-spacing", str(rst)]) == 0
    assert seen["paths"] == [rst]
    assert seen["kwargs"] == {"fix": False}


def test_heading_width_dispatches_to_section_underline_module(monkeypatch, rst: Path):
    seen = _record_run(monkeypatch, "section_underline")
    assert main(["heading-width", "--fix", "--backup-suffix", ".bak", str(rst)]) == 0
    assert seen["paths"] == [rst]
    assert seen["kwargs"] == {
        "fix": True,
        "diff": False,
        "backup_suffix": ".bak",
        "follow_symlinks": False,
    }


def test_sentence_breaks_dispatches_to_sentence_breaks_module(monkeypatch, rst: Path):
    seen = _record_run(monkeypatch, "sentence_breaks")
    assert main(["sentence-breaks", "--follow-symlinks", str(rst)]) == 0
    assert seen["paths"] == [rst]
    assert seen["kwargs"] == {"fix": False, "follow_symlinks": True}


# ---------------------------------------------------------------------------
# heading-width 固有オプション（旧 section-underline から挙動・文言を不変で継承）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode_flag", ["--check", "--fix"])
def test_heading_width_diff_is_exclusive_with_mode_flags(mode_flag: str, rst: Path):
    with pytest.raises(SystemExit) as excinfo:
        main(["heading-width", mode_flag, "--diff", str(rst)])
    assert excinfo.value.code == 2


def test_heading_width_backup_suffix_requires_fix(rst: Path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["heading-width", "--backup-suffix", ".bak", str(rst)])
    assert excinfo.value.code == 2
    assert "--backup-suffix は --fix と併用してください" in capsys.readouterr().err


def test_heading_width_backup_suffix_rejects_empty_string(rst: Path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["heading-width", "--fix", "--backup-suffix", "", str(rst)])
    assert excinfo.value.code == 2
    assert "--backup-suffix には空でない文字列を指定してください" in capsys.readouterr().err


@pytest.mark.parametrize("suffix", ["a/b", "..bak", "a\\b"])
def test_heading_width_backup_suffix_rejects_path_tokens(suffix: str, rst: Path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["heading-width", "--fix", "--backup-suffix", suffix, str(rst)])
    assert excinfo.value.code == 2
    assert "--backup-suffix にパスセパレータや '..' は使用できません" in capsys.readouterr().err


def test_heading_width_fix_conflicts_with_follow_symlinks(rst: Path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["heading-width", "--fix", "--follow-symlinks", str(rst)])
    assert excinfo.value.code == 2
    assert "--fix と --follow-symlinks は併用できません" in capsys.readouterr().err


def test_heading_width_diff_prints_unified_diff_without_writing(tmp_path: Path, caplog):
    import logging

    target = tmp_path / "h.rst"
    target.write_text("見出し\n====\n", encoding="utf-8")
    with caplog.at_level(logging.INFO):
        assert main(["heading-width", "--diff", str(target)]) == 1
    assert target.read_text(encoding="utf-8") == "見出し\n====\n"
    assert any(message.startswith("---") for message in caplog.messages)
    assert any(message.startswith("+++") for message in caplog.messages)


def test_heading_width_backup_suffix_creates_copy(tmp_path: Path):
    target = tmp_path / "h.rst"
    target.write_text("見出し\n====\n", encoding="utf-8")
    assert main(["heading-width", "--fix", "--backup-suffix", ".bak", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == "見出し\n======\n"
    assert (tmp_path / "h.rst.bak").read_text(encoding="utf-8") == "見出し\n====\n"


def test_heading_width_follow_symlinks_includes_link(tmp_path: Path, caplog):
    import logging

    real = tmp_path / "real.rst"
    real.write_text("見出し\n====\n", encoding="utf-8")
    link = tmp_path / "link.rst"
    link.symlink_to(real)

    with caplog.at_level(logging.WARNING):
        assert main(["heading-width", str(link)]) == 1
    assert "シンボリックリンクです" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert main(["heading-width", "--follow-symlinks", str(link)]) == 1
    assert "検出結果: 1 件の違反が見つかりました" in caplog.text
