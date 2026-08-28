"""strong-spacing チェッカーのテスト。"""

from types import SimpleNamespace

import pytest

from tests.inline_corpus import issue_6
from wabun_rst_ulint.checkers import inline_spacing
from wabun_rst_ulint.checkers import strong_emphasis_spacing as strong_spacing
from wabun_rst_ulint.checkers._inline_classifier import classify_document
from wabun_rst_ulint.checkers._inline_model import StrongView


def test_detects_missing_space():
    vs = strong_spacing.find_violations("これは**重要**です\n")
    assert [(v.line, v.kind) for v in vs] == [(1, "前"), (1, "後")]


def test_single_asterisk_emphasis_not_target():
    assert strong_spacing.find_violations("これは*強調*です\n") == []


def test_strong_with_inner_asterisk():
    vs = strong_spacing.find_violations("値**a*b**あ\n")
    assert [(v.line, v.kind) for v in vs] == [(1, "前"), (1, "後")]


def test_allowed_chars():
    assert strong_spacing.find_violations("( **重要** ), **注**.\n") == []


def test_code_block_skipped():
    assert strong_spacing.find_violations(".. code-block:: text\n\n   x**y**z\n") == []


def test_fix_and_idempotent():
    fixed = strong_spacing.fix_text("これは**重要**です\n")
    assert fixed == "これは **重要** です\n"
    assert strong_spacing.fix_text(fixed) == fixed


@pytest.mark.parametrize(
    "source",
    [
        "**x**\r\n",
        "**x**\rnext",
        "before\r**x**",
    ],
)
def test_public_apis_treat_cr_and_lf_as_physical_newline_boundaries(source):
    assert strong_spacing.find_violations(source) == []
    assert strong_spacing.fix_text(source) == source


@pytest.mark.parametrize("case", issue_6.cases(), ids=lambda case: case.id)
def test_issue6_corpus(case):
    fixed = strong_spacing.fix_text(case.source)
    if case.must_fix:
        assert fixed == case.expected
        assert strong_spacing.find_violations(case.source)
    else:
        assert fixed == case.source
        assert strong_spacing.find_violations(case.source) == []
    assert strong_spacing.fix_text(fixed) == fixed


def _inline_fix(source: str) -> str:
    result = inline_spacing.fix_document(source)
    assert result.transaction_failure is False
    return result.text


def test_inline_and_strong_composition_converges_in_both_orders():
    source = "本文**a``code``b**です\n"
    expected = "本文 **a ``code`` b** です\n"

    inline_then_strong = strong_spacing.fix_text(_inline_fix(source))
    strong_then_inline = _inline_fix(strong_spacing.fix_text(source))

    assert inline_then_strong == strong_then_inline == expected
    assert strong_spacing.fix_text(expected) == expected
    assert _inline_fix(expected) == expected


def test_run_check_fix_and_second_pass(tmp_path):
    target = tmp_path / "a.rst"
    target.write_text("本文**a ``code`` b**です\n", encoding="utf-8")

    assert strong_spacing.run([target], fix=False) == 1
    assert strong_spacing.run([target], fix=True) == 0
    assert target.read_text(encoding="utf-8") == "本文 **a ``code`` b** です\n"
    assert strong_spacing.run([target], fix=False) == 0
    assert strong_spacing.run([target], fix=True) == 0


def test_run_skips_strong_fully_inside_literal(tmp_path):
    target = tmp_path / "a.rst"
    source = "``**not-strong**`` です\n"
    target.write_text(source, encoding="utf-8")

    assert strong_spacing.run([target], fix=False) == 0
    assert strong_spacing.run([target], fix=True) == 0
    assert target.read_text(encoding="utf-8") == source


def test_run_preserves_crlf(tmp_path):
    target = tmp_path / "a.rst"
    target.write_bytes("本文**a ``code`` b**です\r\n次行\r\n".encode())

    assert strong_spacing.run([target], fix=True) == 0
    assert target.read_bytes() == "本文 **a ``code`` b** です\r\n次行\r\n".encode()


def test_run_classifies_once_per_file(tmp_path, monkeypatch):
    target = tmp_path / "a.rst"
    target.write_text("本文**重要**です\n", encoding="utf-8")
    real_classify = strong_spacing.classify_document
    calls = 0

    def counted(source):
        nonlocal calls
        calls += 1
        return real_classify(source)

    monkeypatch.setattr(strong_spacing, "classify_document", counted)

    assert strong_spacing.run([target], fix=True) == 0
    assert calls == 1


@pytest.mark.parametrize(
    ("source", "recognized", "expected"),
    [
        ("本文 **重要** です\n", True, "本文 **重要** です\n"),
        (
            "本文**a ``code`` b**です\n",
            False,
            "本文 **a ``code`` b** です\n",
        ),
    ],
)
def test_consumes_recognized_and_boundary_deficient_owners(source, recognized, expected):
    owner = classify_document(source).strong.owners[0]
    assert owner.recognized_by_docutils is recognized

    plan = strong_spacing.build_edit_plan(source, (owner,))

    assert plan.text == expected


def test_edit_plan_changes_only_external_boundaries():
    source = "前**a ``code`` b**後\n"
    owner = classify_document(source).strong.owners[0]
    outer = source[owner.source_range.start : owner.source_range.end]
    interior = source[owner.interior_range.start : owner.interior_range.end]

    plan = strong_spacing.build_edit_plan(source, (owner,))

    assert plan.text == f"前 {outer} 後\n"
    assert outer == "**a ``code`` b**"
    assert interior == "a ``code`` b"
    assert plan.insertion_offsets == (
        owner.source_range.start,
        owner.source_range.end,
    )


@pytest.mark.parametrize(
    "source",
    [
        "``**not-strong**`` です\n",
        "\\**strong**直後\n",
        "これは*強調*です\n",
    ],
)
def test_non_owned_or_single_emphasis_is_untouched(source):
    assert classify_document(source).strong.owners == ()
    assert strong_spacing.fix_text(source) == source


def test_consumer_does_not_inspect_inline_view(monkeypatch):
    source = "本文**重要**です\n"

    class StrongOnlyViews(SimpleNamespace):
        strong = StrongView(owners=())

        @property
        def inline(self):
            raise AssertionError("strong-spacing must not inspect InlineView")

    monkeypatch.setattr(
        strong_spacing,
        "classify_document",
        lambda _source: StrongOnlyViews(),
    )

    assert strong_spacing.fix_text(source) == source
