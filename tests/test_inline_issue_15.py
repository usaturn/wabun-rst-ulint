"""Focused Issue #15 bounded-convergence contract."""

from __future__ import annotations

from tests.helpers.bounded_fixer import bounded_fixer
from tests.inline_corpus.issue_15 import cases


def test_role_and_literal_adjacent_repair_converges_by_third_invocation(monkeypatch):
    case = cases()[0]
    fix = bounded_fixer(monkeypatch)
    first = fix(case.source)
    assert first.text == case.first_expected
    assert first.changed is True
    second = fix(first.text)
    assert second.text == case.fixed_point
    assert second.changed is True
    third = fix(second.text)
    assert third.text == case.fixed_point
    assert third.changed is False
