"""inline-spacing --syntax-only の判定・修正・CLI（Issue #2）。

入力は Issue #2 の決定コメント（受け入れの例）と #1 の英文の例である。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wabun_rst_ulint.checkers import inline_spacing
from wabun_rst_ulint.checkers._inline_classifier import classify_document
from wabun_rst_ulint.cli import main

_REPORTED = ("accepted", "report_only")

# 開始記号の前だけが欠け、直前が文字・数字。--fix で空白を入れる（入力, 修正後）
FIXABLE = [
    ("A the:ref:`roles` page.\n", "A the :ref:`roles` page.\n"),
    ("B the``queue`` value.\n", "B the ``queue`` value.\n"),
    (
        "C the`Example <https://example.com>`__ link.\n",
        "C the `Example <https://example.com>`__ link.\n",
    ),
    (
        "D the`Example`_ link.\n\n.. _Example: https://example.com\n",
        "D the `Example`_ link.\n\n.. _Example: https://example.com\n",
    ),
    ("E the:term:`queue` here.\n", "E the :term:`queue` here.\n"),
    ("F the_`inline target` here.\n", "F the _`inline target` here.\n"),
    ("値は``foo`` です\n", "値は ``foo`` です\n"),
    ("version2``x`` here.\n", "version2 ``x`` here.\n"),
    # 直前の URL は docutils が記法の解析の後で認識するので、隣接の補正の対象外
    ("see https://example.com``x`` now.\n", "see https://example.com ``x`` now.\n"),
]

# docutils が認識しない境界のうち、--fix では直さないもの
REPORT_ONLY = [
    "G see :ref:`roles`page now.\n",
    "H see ``queue``value now.\n",
    "I see `Example <https://example.com>`__now.\n",
    "two ``queue``s and ``other`` here.\n",
    "set FOO=``bar`` now.\n",
    "see ``f``() and ``g`` here.\n",
    "e.g.``x`` here.\n",
    "値は``foo``です\n",
]

# docutils が記法の境界と認識するので違反にしない
RECOGNIZED = [
    "J (:ref:`roles`) and :ref:`roles`, and :ref:`roles`'s end.\n",
    'K "``queue``" here.\n',
    "two ``queue``\\ s here.\n",
    "see :ref:`a`:ref:`b` here.\n",
    "これは :term:`X`。\n",
    "x ``a`` y and x\t``b``\ty and x　``c``　y\n",
    "L code block follows ::\n\n    the:ref:`roles` inside literal block\n",
    "A ``lit``. B :func:`f`, C :func:`g`. D `link <https://e.x>`_. "
    "E :func:`h`) F (:func:`i`) G :func:`j`: K ``k``; L :ref:`m`!\n",
    ":ref:`a` at the start of the file.\n",
    "no newline at the end ``y``",
]


def _reported(source: str):
    views = classify_document(source, syntax_only=True)
    return [decision for decision in views.inline.decisions if decision.status in _REPORTED]


@pytest.mark.parametrize(("source", "_fixed"), FIXABLE)
def test_fixable_start_boundary_is_reported_as_accepted(source: str, _fixed: str):
    reported = _reported(source)
    assert [decision.status for decision in reported] == ["accepted"]
    assert len(inline_spacing.check_document(source, syntax_only=True).violations) == 1


@pytest.mark.parametrize("source", REPORT_ONLY)
def test_unrecognized_boundary_is_report_only(source: str):
    reported = _reported(source)
    assert reported
    assert {decision.status for decision in reported} == {"report_only"}
    assert {decision.reason for decision in reported} <= {
        "unrecognized-start",
        "unrecognized-end",
        "unrecognized-start-end",
    }


@pytest.mark.parametrize("source", RECOGNIZED)
def test_recognized_boundaries_are_not_violations(source: str):
    assert inline_spacing.check_document(source, syntax_only=True).violations == ()


def test_fixable_violation_uses_the_default_message():
    (violation,) = inline_spacing.check_document("B the``queue`` value.\n", syntax_only=True).violations
    assert violation.line == 1
    assert violation.text == "literal の外部境界空白が不正（'``queue``' → ' ``queue``'）"


@pytest.mark.parametrize(
    ("source", "detail"),
    [
        ("H see ``queue``value now.\n", "終了記号の後: '``queue``v'"),
        ("set FOO=``bar`` now.\n", "開始記号の前: '=``bar``'"),
        ("x the``queue``value now.\n", "開始記号の前と終了記号の後: 'e``queue``v'"),
    ],
)
def test_report_only_message_names_the_side(source: str, detail: str):
    (violation,) = inline_spacing.check_document(source, syntax_only=True).violations
    assert violation.line == 1
    assert violation.text == f"literal の外部境界を docutils が認識しない（{detail}、--fix では修正しない）"


@pytest.mark.parametrize(("source", "fixed"), FIXABLE)
def test_fix_inserts_space_before_start(source: str, fixed: str):
    result = inline_spacing.fix_document(source, syntax_only=True)
    assert result.transaction_failure is False
    assert result.text == fixed
    assert result.remaining == ()
    assert inline_spacing.fix_document(fixed, syntax_only=True).changed is False


@pytest.mark.parametrize("source", REPORT_ONLY)
def test_fix_leaves_report_only_boundaries(source: str):
    result = inline_spacing.fix_document(source, syntax_only=True)
    assert result.changed is False
    assert result.transaction_failure is False
    assert result.remaining == inline_spacing.check_document(source, syntax_only=True).violations


def test_fix_keeps_report_only_violations_as_remaining():
    source = "A the:ref:`roles` page.\n\nH see ``queue``value now.\n"
    (fixable, report_only) = inline_spacing.check_document(source, syntax_only=True).violations
    result = inline_spacing.fix_document(source, syntax_only=True)
    assert result.text == "A the :ref:`roles` page.\n\nH see ``queue``value now.\n"
    assert result.violations == (fixable,)
    assert result.remaining == (report_only,)
    assert inline_spacing.check_document(result.text, syntax_only=True).violations == (report_only,)


def _write_rst(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "doc.rst"
    path.write_text(text, encoding="utf-8")
    return path


def test_cli_english_text_passes_only_with_syntax_only(tmp_path: Path):
    path = _write_rst(tmp_path, RECOGNIZED[0])
    assert main(["inline-spacing", str(path)]) == 1
    assert main(["inline-spacing", "--syntax-only", str(path)]) == 0
    assert main(["inline-spacing", "--check", "--syntax-only", str(path)]) == 0


def test_cli_fix_writes_fixable_and_reports_remaining(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    path = _write_rst(tmp_path, "A the:ref:`roles` page.\n\nH see ``queue``value now.\n")
    assert main(["inline-spacing", "--fix", "--syntax-only", str(path)]) == 1
    assert path.read_text(encoding="utf-8") == "A the :ref:`roles` page.\n\nH see ``queue``value now.\n"
    err = capsys.readouterr().err
    assert f"修正: {path}（1 箇所）" in err
    assert f"{path}:3: literal の外部境界を docutils が認識しない" in err


def test_cli_fix_report_only_file_is_unchanged_and_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    path = _write_rst(tmp_path, REPORT_ONLY[1])
    assert main(["inline-spacing", "--fix", "--syntax-only", str(path)]) == 1
    assert path.read_text(encoding="utf-8") == REPORT_ONLY[1]
    assert f"{path}:1: literal の外部境界を docutils が認識しない" in capsys.readouterr().err


def test_cli_fix_all_fixable_exits_0(tmp_path: Path):
    source, fixed = FIXABLE[0]
    path = _write_rst(tmp_path, source)
    assert main(["inline-spacing", "--fix", "--syntax-only", str(path)]) == 0
    assert path.read_text(encoding="utf-8") == fixed
