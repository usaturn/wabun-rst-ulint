"""heading-width チェッカー（section_underline 実装モジュール）のテスト。"""

from pathlib import Path

from wabun_rst_ulint.checkers.section_underline import find_violations, fix_text, run


def test_cjk_width_short_underline_detected():
    vs = find_violations("日本語見出し\n====\n")
    assert len(vs) == 1
    assert vs[0].kind == "セクション下線"
    assert "width=12" in vs[0].text


def test_correct_width_ok():
    assert find_violations("日本語見出し\n============\n") == []
    assert find_violations("ascii title\n-----------\n") == []


def test_overline_pair_detected_and_fixed():
    text = "====\n見出し\n======\n"
    vs = find_violations(text)
    assert len(vs) == 1
    assert vs[0].kind == "セクション上下線"
    assert fix_text(text) == "======\n見出し\n======\n"


def test_fix_underline_and_idempotent():
    fixed = fix_text("日本語見出し\n====\n")
    assert fixed == "日本語見出し\n============\n"
    assert fix_text(fixed) == fixed


def test_adornment_inside_code_block_ignored():
    text = ".. code-block:: text\n\n   ====\n"
    assert find_violations(text) == []


def test_run_fix_writes_file(tmp_path: Path):
    target = tmp_path / "a.rst"
    target.write_text("見出し\n====\n", encoding="utf-8")
    assert run([target], fix=False, diff=False, backup_suffix=None, follow_symlinks=False) == 1
    assert run([target], fix=True, diff=False, backup_suffix=None, follow_symlinks=False) == 0
    assert target.read_text(encoding="utf-8") == "見出し\n======\n"


def test_run_backup_suffix_creates_copy(tmp_path: Path):
    target = tmp_path / "a.rst"
    target.write_text("見出し\n====\n", encoding="utf-8")
    assert run([target], fix=True, diff=False, backup_suffix=".bak", follow_symlinks=False) == 0
    assert (tmp_path / "a.rst.bak").read_text(encoding="utf-8") == "見出し\n====\n"


def test_run_diff_mode_does_not_write(tmp_path: Path, caplog):
    import logging

    target = tmp_path / "a.rst"
    target.write_text("見出し\n====\n", encoding="utf-8")
    with caplog.at_level(logging.INFO):
        code = run([target], fix=False, diff=True, backup_suffix=None, follow_symlinks=False)
    assert code == 1
    assert target.read_text(encoding="utf-8") == "見出し\n====\n"
    assert any(m.startswith("---") for m in caplog.messages)
    assert any(m.startswith("+++") for m in caplog.messages)


def test_run_preserves_permissions(tmp_path: Path):
    target = tmp_path / "a.rst"
    target.write_text("見出し\n====\n", encoding="utf-8")
    target.chmod(0o640)
    run([target], fix=True, diff=False, backup_suffix=None, follow_symlinks=False)
    assert (target.stat().st_mode & 0o777) == 0o640
