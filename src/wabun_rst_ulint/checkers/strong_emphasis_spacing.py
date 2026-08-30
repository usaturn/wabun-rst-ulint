"""RST 強調表示（strong emphasis）のスペースチェック・修正スクリプト（CLI 公開名: strong-spacing）

reStructuredText の強調表示記法 **...** の前後に必要な
半角スペースが不足している箇所を検出し、--fix オプションで自動修正する。

sphinx(docutils) の強調表示はダブルアスタリスクの外側に
半角スペースが必要であり、日本語テキスト中でスペースが抜けると
レンダリングが崩れる原因となる。

なお、本スクリプトは strong emphasis（ダブルアスタリスク **...**）のみを
対象とし、単一アスタリスクの emphasis（*...*）は対象外とする。

使用例:
    uv run wabun-rst-ulint strong-spacing source/
    uv run wabun-rst-ulint strong-spacing source/example.rst
    uv run wabun-rst-ulint strong-spacing --fix source/ docs/
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from wabun_rst_ulint.checkers import _checker_runner
from wabun_rst_ulint.checkers._inline_classifier import classify_document
from wabun_rst_ulint.checkers._inline_model import StrongOwner
from wabun_rst_ulint.reporting import Violation


def find_violations(text: str) -> list[Violation]:
    """テキスト全体のスペース不足違反を返す。"""
    return list(_analyze(text).violations)


def fix_text(text: str) -> str:
    """違反位置に半角スペースを挿入した全文を返す（冪等）。"""
    return _analyze(text).text


_ALLOWED_BEFORE = frozenset({" ", "(", "[", "{", "<", "-", "/", ":", "'", '"', "\\"})
_ALLOWED_AFTER = frozenset({" ", ".", ",", ";", ":", "!", "?", ")", "]", "}", ">", "-", "/", "'", '"', "\\"})


@dataclass(frozen=True)
class StrongEditPlan:
    """Strong owner の external boundary だけを変更する pure plan。"""

    violations: tuple[Violation, ...]
    insertion_offsets: tuple[int, ...]
    text: str


def _needs_before_space(source: str, start: int) -> bool:
    return start > 0 and source[start - 1] not in "\r\n" and source[start - 1] not in _ALLOWED_BEFORE


def _needs_after_space(source: str, end: int) -> bool:
    return end < len(source) and source[end] not in "\r\n" and source[end] not in _ALLOWED_AFTER


def _line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _violation(source: str, owner: StrongOwner, *, offset: int, kind: str) -> Violation:
    raw = source[owner.source_range.start : owner.source_range.end]
    return Violation(
        line=_line_number(source, offset),
        kind=kind,
        text=f"strong の外部境界に半角スペースが必要（{kind}: {raw!r}）",
    )


def _apply_insertions(source: str, offsets: tuple[int, ...]) -> str:
    text = source
    for offset in reversed(offsets):
        text = f"{text[:offset]} {text[offset:]}"
    return text


def build_edit_plan(source: str, owners: tuple[StrongOwner, ...]) -> StrongEditPlan:
    violations: list[Violation] = []
    insertions: set[int] = set()
    ordered = sorted(owners, key=lambda owner: owner.source_range.start)
    for owner in ordered:
        start = owner.source_range.start
        end = owner.source_range.end
        if _needs_before_space(source, start):
            violations.append(_violation(source, owner, offset=start, kind="前"))
            insertions.add(start)
        if _needs_after_space(source, end):
            violations.append(_violation(source, owner, offset=end, kind="後"))
            insertions.add(end)
    offsets = tuple(sorted(insertions))
    return StrongEditPlan(
        violations=tuple(violations),
        insertion_offsets=offsets,
        text=_apply_insertions(source, offsets),
    )


def _analyze(text: str) -> StrongEditPlan:
    views = classify_document(text)
    return build_edit_plan(text, views.strong.owners)


def run(paths: Sequence[str | Path], *, fix: bool) -> int:
    """Typed StrongView consumer を共通 runner で検査・修正する。"""

    def process(text: str) -> _checker_runner.RunOutcome:
        plan = _analyze(text)
        return _checker_runner.RunOutcome(
            violations=plan.violations,
            fixed_text=plan.text if fix and plan.text != text else None,
        )

    return _checker_runner.run_checker(paths, fix=fix, process=process)
