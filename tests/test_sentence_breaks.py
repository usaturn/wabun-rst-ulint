"""sentence-breaks チェッカーのテスト。"""

from pathlib import Path

import pytest

import wabun_rst_ulint.checkers.sentence_breaks as sentence_breaks
from wabun_rst_ulint.checkers.sentence_breaks import _apply_edits, _Edit, find_violations, fix_text, run


def test_rule1_midline_period_detected():
    vs = find_violations("一文目。二文目\n\n")
    assert [(v.line, v.kind) for v in vs] == [(1, "Rule1")]


def test_find_reports_rule1_before_rule23_on_same_original_line():
    violations = find_violations("一文目。文末。\n\n")
    assert [(item.line, item.kind) for item in violations] == [
        (1, "Rule1"),
        (1, "Rule2/3"),
    ]


def test_fix_preserves_two_stage_structural_marker_outputs():
    assert fix_text("本文です。====\n") == "本文です\n====\n"
    assert fix_text("本文です。::\n") == "本文です\n::\n"
    assert fix_text("。   ::* \n") == "\n::* \n"


def test_fix_preserves_field_continuation_indent_and_directive_intro():
    assert fix_text(":項目: 一文目。二文目\n") == ":項目: 一文目。\n     二文目\n"
    directive = ".. note:: 一文目。二文目\n"
    assert fix_text(directive) == directive
    assert fix_text("文末。") == "文末"


def test_same_start_deletion_precedes_insertion():
    edits = [_Edit(1, 1, "\n"), _Edit(1, 2, "")]
    assert _apply_edits("。。", edits) == "。\n"


def test_known_double_period_legacy_first_pass_is_unchanged():
    assert fix_text("。。") == "。\n"
    assert fix_text(fix_text("。。")) == "\n"


def test_rule1_period_inside_brackets_kept():
    assert find_violations("補足（注記。続き）は維持\n\n") == []


def test_rule23_block_end_period_detected():
    vs = find_violations("文末に句点。\n\n次の段落\n")
    assert [(v.line, v.kind) for v in vs] == [(1, "Rule2/3")]


def test_code_block_untouched():
    text = "例::\n\n   コード。そのまま。\n"
    assert find_violations(text) == []
    assert fix_text(text) == text


def test_fix_rule1_splits_with_list_indent():
    fixed = fix_text("#. 項目の一文目。二文目\n")
    assert fixed == "#. 項目の一文目。\n   二文目\n"


def test_fix_rule23_removes_trailing_period():
    assert fix_text("文末に句点。\n\n次\n") == "文末に句点\n\n次\n"


def test_fix_idempotent():
    fixed = fix_text("一文目。二文目。\n\n")
    assert fix_text(fixed) == fixed


def test_run_check_exit_1_and_fix(tmp_path: Path, capsys):
    target = tmp_path / "a.rst"
    target.write_text("一文目。二文目\n\n", encoding="utf-8")
    assert run([target], fix=False) == 1
    assert "[Rule1]" in capsys.readouterr().out
    assert run([target], fix=True) == 0
    assert "修正: " in capsys.readouterr().out
    assert run([target], fix=False) == 0


def test_direct_apis_propagate_classification_failure(monkeypatch):
    def fail(_source: str):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(sentence_breaks, "classify_document", fail)
    with pytest.raises(RuntimeError, match="classifier unavailable"):
        find_violations("本文。続き\n")
    with pytest.raises(RuntimeError, match="classifier unavailable"):
        fix_text("本文。続き\n")


@pytest.mark.parametrize("fix", [False, True])
def test_run_classification_failure_is_file_local_no_write_and_exit_2(tmp_path, capsys, monkeypatch, fix):
    bad = tmp_path / "a_bad.rst"
    bad_source = "分類失敗。保持\n"
    bad.write_text(bad_source, encoding="utf-8")
    good = tmp_path / "b_good.rst"
    good.write_text("通常。続き\n", encoding="utf-8")

    real = sentence_breaks.classify_document

    def fail_one(source: str):
        if source == bad_source:
            raise RuntimeError("boom")
        return real(source)

    monkeypatch.setattr(sentence_breaks, "classify_document", fail_one)
    assert run([bad, good], fix=fix) == 2
    captured = capsys.readouterr()
    assert f"分類失敗: {bad}: boom" in captured.err
    assert bad.read_text(encoding="utf-8") == bad_source
    if fix:
        assert good.read_text(encoding="utf-8") == "通常。\n続き\n"
    else:
        assert f"{good}:1: [Rule1]" in captured.out


def test_run_read_error_exit_2(tmp_path: Path, capsys, monkeypatch):
    bad = tmp_path / "nope.rst"
    bad.write_text("あ\n", encoding="utf-8")

    real_read_text = Path.read_text

    def failing_read_text(self, *args, **kwargs):
        if self.name == "nope.rst":
            raise OSError("Permission denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", failing_read_text)
    assert run([bad], fix=False) == 2
    assert "読み込み失敗" in capsys.readouterr().err


def test_fix_continues_after_write_error(tmp_path: Path, capsys, monkeypatch):
    bad = tmp_path / "a.rst"
    bad.write_text("あ。い\n", encoding="utf-8")
    good = tmp_path / "b.rst"
    good.write_text("う。え\n", encoding="utf-8")

    real_write_text = Path.write_text

    def failing_write_text(self, *args, **kwargs):
        if self.name == "a.rst":
            raise OSError("Read-only file system")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)
    assert run([bad, good], fix=True) == 2

    captured = capsys.readouterr()
    assert "書き込み失敗: " in captured.err
    # a.rst で中断せず b.rst まで修正されている
    assert good.read_text(encoding="utf-8") == "う。\nえ\n"


def test_run_directory_expands_rst_files(tmp_path: Path, capsys):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "a.rst").write_text("あ。い\n", encoding="utf-8")
    assert run([d], fix=False) == 1
    out = capsys.readouterr().out
    assert "a.rst:1: [Rule1]" in out


def test_run_empty_directory_is_error(tmp_path: Path, capsys):
    d = tmp_path / "empty"
    d.mkdir()
    assert run([d], fix=False) == 1
    assert ".rst ファイルが見つかりませんでした" in capsys.readouterr().err


def test_run_continues_after_unicode_decode_error(tmp_path: Path, capsys):
    bad = tmp_path / "a_bad.rst"
    bad.write_bytes(b"\x93\xfa\x96\x7b")  # Shift-JIS バイト列
    good = tmp_path / "b_good.rst"
    good.write_text("あ。い\n", encoding="utf-8")
    assert run([tmp_path], fix=False) == 2
    captured = capsys.readouterr()
    assert "読み込み失敗" in captured.err
    # a_bad.rst で中断せず b_good.rst も検査されている
    assert "b_good.rst:1: [Rule1]" in captured.out


def test_run_excludes_venv_rst(tmp_path: Path, capsys):
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "pkg.rst").write_text("あ。い\n", encoding="utf-8")
    normal = tmp_path / "a.rst"
    normal.write_text("あ。い\n", encoding="utf-8")
    assert run([tmp_path], fix=False) == 1
    out = capsys.readouterr().out
    assert "a.rst:1:" in out
    assert ".venv" not in out
