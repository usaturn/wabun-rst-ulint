"""inline-spacing --syntax-only の判定・修正・CLI（Issue #2）。

入力は Issue #2 の決定コメント（受け入れの例）と #1 の英文の例である。
"""

from __future__ import annotations

import pytest

from wabun_rst_ulint.checkers import inline_spacing
from wabun_rst_ulint.checkers._inline_classifier import classify_document

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
