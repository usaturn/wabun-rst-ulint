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

# 前方に置くと、記法の rawsource とソースの対応付けが崩れていた構成
_EMBEDDED_LINK = "See `Example <https://example.com>`_.\n\n"
_SUBSTITUTION_IMAGE = "See |logo| here.\n\n.. |logo| image:: logo.png\n\n"
# 置換定義の中の記法は参照の位置にも同じ rawsource で現れ、対応付けがそこで止まる
_TRUNCATING = ".. |name| replace:: :emphasis:`x`\n\nSee |name|.\n\n"

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
    ("the`path` here.\n", "the `path` here.\n"),
    # interpreted text の本文のバックスラッシュは、境界の認識に関わらない
    ("the`C:\\path` here.\n", "the `C:\\path` here.\n"),
    # 直前が文字なら、前方の構成（埋め込み URI 付きのリンク）によらず直す
    (_EMBEDDED_LINK + "A the:ref:`roles` page.\n", _EMBEDDED_LINK + "A the :ref:`roles` page.\n"),
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
    "see `foo\\bar`now.\n",
    # 前の記法と境界を共有するリテラル。区切りが曖昧なので直さない
    "`name`_``code`` here.\n",
    "x `ab``c`` here.\n",
    # 対応付けが止まった後でも、終了記号の後は前方の構成によらず判定できる
    _TRUNCATING + "see :ref:`a`:ref:`b`now.\n",
]

# 記法の直後の開始記号。前方の構成によらず、docutils は認識する
RECOGNIZED_AFTER_PRECEDING_CONTENT = [
    _EMBEDDED_LINK + "see :ref:`a`:ref:`b` here.\n",
    _SUBSTITUTION_IMAGE + "see :ref:`a`:ref:`b` here.\n",
    ".. :ref:`a`\n\nsee :ref:`a`:ref:`b` here.\n",
    "Example::\n\n    :ref:`a`\n\nsee :ref:`a`:ref:`b` here.\n",
    _EMBEDDED_LINK + "The ``queue``:ref:`x` entry.\n",
    # 対応付けが止まった後は認識済みの終わりが分からないので、違反にしない
    _TRUNCATING + "see :ref:`a`:ref:`b`.\n",
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
    "see `C:\\path` here.\n",
    *RECOGNIZED_AFTER_PRECEDING_CONTENT,
]

# 既定の規則では違反にしない入力（syntax-only の判定とは別に、既定の規則の結果を保つ）
DEFAULT_RULE_UNREPORTED = [
    "the`C:\\path` here.\n",
    "see `foo\\bar`now.\n",
    "`name`_``code`` here.\n",
]

# Issue #2 本文の en.rst（A〜L）
ISSUE_2_EN = """Title
=====

A the:ref:`roles` page.

B the``queue`` value.

C the`Example <https://example.com>`__ link.

D the`Example`_ link.

E the:term:`queue` here.

F the_`inline target` here.

G see :ref:`roles`page now.

H see ``queue``value now.

I see `Example <https://example.com>`__now.

J (:ref:`roles`) and :ref:`roles`, and :ref:`roles`'s end.

K "``queue``" here.

L code block follows ::

    the:ref:`roles` inside literal block
"""
ISSUE_2_EN_FIXED = (
    ISSUE_2_EN.replace("A the:ref:", "A the :ref:")
    .replace("B the``", "B the ``")
    .replace("C the`", "C the `")
    .replace("D the`", "D the `")
    .replace("E the:term:", "E the :term:")
    .replace("F the_`", "F the _`")
)
# G・H・I の行
ISSUE_2_EN_REPORT_ONLY_LINES = [16, 18, 20]

# 直せる違反の後に、直さない違反が残る（入力, 修正後, 残る違反の行）
FIXABLE_BEFORE_REPORT_ONLY = [
    (
        "B the``queue`` value.\n\nH see ``queue``value now.\n",
        "B the ``queue`` value.\n\nH see ``queue``value now.\n",
        [3],
    ),
    (
        "Run the``build`` command, then see ``queue``value.\n",
        "Run the ``build`` command, then see ``queue``value.\n",
        [1],
    ),
    (ISSUE_2_EN, ISSUE_2_EN_FIXED, ISSUE_2_EN_REPORT_ONLY_LINES),
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


def test_letter_before_start_is_reported_after_truncated_alignment():
    source = _TRUNCATING + "the:ref:`x` page.\n"
    assert [decision.status for decision in _reported(source)] == ["accepted"]
    assert len(inline_spacing.check_document(source, syntax_only=True).violations) == 1


def test_start_after_markup_is_unsupported_after_truncated_alignment():
    views = classify_document(_TRUNCATING + "see :ref:`a`:ref:`b`.\n", syntax_only=True)
    assert [(decision.status, decision.reason) for decision in views.inline.decisions] == [
        ("unsupported", "alignment-truncated")
    ]


@pytest.mark.parametrize("source", DEFAULT_RULE_UNREPORTED)
def test_default_rule_does_not_report_escaped_or_shared_boundary(source: str):
    assert inline_spacing.check_document(source).violations == ()
    assert inline_spacing.fix_document(source).changed is False


@pytest.mark.parametrize(("source", "fixed", "remaining_lines"), FIXABLE_BEFORE_REPORT_ONLY)
def test_fix_writes_fixable_before_report_only(source: str, fixed: str, remaining_lines: list[int]):
    result = inline_spacing.fix_document(source, syntax_only=True)
    assert result.transaction_failure is False
    assert result.text == fixed
    assert [violation.line for violation in result.remaining] == remaining_lines
    assert inline_spacing.check_document(fixed, syntax_only=True).violations == result.remaining


def test_fix_still_refuses_new_system_message_next_to_report_only():
    # 直すと見出しが下線より長くなり、警告が増える
    source = "Use the``True``\n===============\n\nH see ``queue``value now.\n"
    result = inline_spacing.fix_document(source, syntax_only=True)
    assert result.transaction_failure is True
    assert result.changed is False
    assert result.text == source


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


@pytest.mark.parametrize(
    ("source", "check_exit", "fix_exit", "fixed"),
    [
        *[(source, 0, 0, source) for source in RECOGNIZED_AFTER_PRECEDING_CONTENT],
        ("the`C:\\path` here.\n", 1, 0, "the `C:\\path` here.\n"),
        ("see `foo\\bar`now.\n", 1, 1, "see `foo\\bar`now.\n"),
        ("`name`_``code`` here.\n", 1, 1, "`name`_``code`` here.\n"),
        (ISSUE_2_EN, 1, 1, ISSUE_2_EN_FIXED),
    ],
)
def test_cli_syntax_only_exit_codes(tmp_path: Path, source: str, check_exit: int, fix_exit: int, fixed: str):
    path = _write_rst(tmp_path, source)
    assert main(["inline-spacing", "--syntax-only", str(path)]) == check_exit
    assert main(["inline-spacing", "--fix", "--syntax-only", str(path)]) == fix_exit
    assert path.read_text(encoding="utf-8") == fixed
