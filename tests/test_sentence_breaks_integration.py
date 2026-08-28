"""SentenceView と sentence-breaks の sentence rules の結合テスト。"""

import ast
import inspect

import pytest

import wabun_rst_ulint.checkers.sentence_breaks as sentence_breaks
from wabun_rst_ulint.checkers.sentence_breaks import find_violations, fix_text


@pytest.mark.parametrize(
    "source",
    [
        "本文 ``リテラル。続き`` です\n",
        "本文 :ref:`参照。続き` です\n",
        "本文 `参照。続き`_ です\n",
        "本文 **強調。続き** です\n",
        "本文 *強調。続き* です\n",
        "本文 :term:`用語。続き` です\n",
    ],
)
def test_rule1_punctuation_inside_recognized_sentence_ranges_is_protected(source: str):
    assert find_violations(source) == []
    assert fix_text(source) == source


def test_find_violations_classifies_exactly_once(monkeypatch):
    calls = 0
    real = sentence_breaks.classify_document

    def counted(source: str):
        nonlocal calls
        calls += 1
        return real(source)

    monkeypatch.setattr(sentence_breaks, "classify_document", counted)
    assert [(v.line, v.kind) for v in find_violations("一文目。二文目\n")] == [(1, "Rule1")]
    assert calls == 1


def test_fix_text_classifies_exactly_once(monkeypatch):
    calls = 0
    real = sentence_breaks.classify_document

    def counted(source: str):
        nonlocal calls
        calls += 1
        return real(source)

    monkeypatch.setattr(sentence_breaks, "classify_document", counted)
    assert fix_text("一文目。二文目\n") == "一文目。\n二文目\n"
    assert calls == 1


def test_protected_and_unprotected_punctuation_compose_on_one_line():
    source = "外側。続き ``内側。保持`` です\n"
    assert fix_text(source) == "外側。\n続き ``内側。保持`` です\n"


@pytest.mark.parametrize(
    "source",
    [
        "本文``リテラル。続き``です\n",
        "本文:ref:`参照。続き`です\n",
        "本文*強調。続き*です\n",
    ],
)
def test_boundary_deficient_closed_tokens_are_protected(source: str):
    assert find_violations(source) == []
    assert fix_text(source) == source


def test_rule23_protected_multiline_literal_and_unprotected_control():
    protected = "本文 ``リテラル。\n====``\n\n次段落\n"
    control = "本文 リテラル。\n====\n\n次段落\n"

    assert find_violations(protected) == []
    assert fix_text(protected) == protected
    assert [(v.line, v.kind) for v in find_violations(control)] == [(1, "Rule2/3")]
    assert fix_text(control) == "本文 リテラル\n====\n\n次段落\n"


@pytest.mark.parametrize(
    "source",
    [
        "本文 `未終端。続き\n",
        "本文 *未終端。続き\n",
        "本文 **未終端。続き\n",
    ],
)
def test_unsupported_physical_line_is_silent_noop(source: str, capsys):
    assert find_violations(source) == []
    assert fix_text(source) == source
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("``docs/*.rst`` を対象とする。次の文があります。\n", "``docs/*.rst`` を対象とする。\n次の文があります\n"),
        ("計算は 2 * 3 = 6 です。次の文があります。\n", "計算は 2 * 3 = 6 です。\n次の文があります\n"),
        (".. [*] 脚注本文です。次の文があります。\n", ".. [*] 脚注本文です。\n次の文があります\n"),
        ("* 箇条書き。続きの文。\n", "* 箇条書き。\n  続きの文\n"),
        (r"本文 \* は通常文字です。次の文。" + "\n", "本文 \\* は通常文字です。\n次の文\n"),
        (r"本文 \` は通常文字です。次の文。" + "\n", "本文 \\` は通常文字です。\n次の文\n"),
    ],
)
def test_supported_asterisk_controls_remain_editable(source: str, expected: str):
    assert fix_text(source) == expected


TRUNCATING = "冒頭 ``head`` です。\n\n- 項目 **重要\n  箇所** です\n\n後続 **ok** と ``tail`` です。\n"


def test_only_unsupported_physical_line_is_skipped():
    source = "前。続き\n本文 *未終端。保持\n後。続き\n"
    assert fix_text(source) == "前。\n続き\n本文 *未終端。保持\n後。\n続き\n"


def test_alignment_truncation_suffix_is_silent_noop(capsys):
    assert find_violations(TRUNCATING) == []
    assert fix_text(TRUNCATING) == TRUNCATING
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_crlf_offsets_and_lf_only_line_numbers_stay_aligned():
    source = "本文 ``リテラル。続き`` です。次です\r\n\r\n次段落\r\n"
    assert [(v.line, v.kind) for v in find_violations(source)] == [(1, "Rule1")]
    assert fix_text(source) == "本文 ``リテラル。続き`` です。\n次です\r\n\r\n次段落\r\n"


STABLE_SOURCES = (
    "一文目。二文目。\n\n",
    "補足（注記。続き）は維持\n\n",
    "文末に句点。\n\n次\n",
    "例::\n\n   コード。そのまま。\n",
    "#. 項目の一文目。二文目\n",
    ":項目: 一文目。二文目\n",
    ".. note:: 一文目。二文目\n",
    "本文です。====\n",
    "本文です。::\n",
    "。   ::* \n",
    "本文 ``リテラル。続き`` です\n",
    "本文 :ref:`参照。続き` です\n",
    "本文 `参照。続き`_ です\n",
    "本文 **強調。続き** です\n",
    "本文 *強調。続き* です\n",
    "本文 :term:`用語。続き` です\n",
    "本文``リテラル。続き``です\n",
    "本文:ref:`参照。続き`です\n",
    "本文*強調。続き*です\n",
    "本文 `未終端。続き\n",
    "本文 *未終端。続き\n",
    "本文 **未終端。続き\n",
    "外側。続き ``内側。保持`` です\n",
    "``docs/*.rst`` を対象とする。次の文があります。\n",
    "計算は 2 * 3 = 6 です。次の文があります。\n",
    ".. [*] 脚注本文です。次の文があります。\n",
    "* 箇条書き。続きの文。\n",
    r"本文 \* は通常文字です。次の文。" + "\n",
    r"本文 \` は通常文字です。次の文。" + "\n",
    "前。続き\n本文 *未終端。保持\n後。続き\n",
    "本文 ``リテラル。\n====``\n\n次段落\n",
    "本文 リテラル。\n====\n\n次段落\n",
    "本文 ``リテラル。続き`` です。次です\r\n\r\n次段落\r\n",
    TRUNCATING,
)


@pytest.mark.parametrize("source", STABLE_SOURCES)
def test_declared_sentence_source_fixtures_gain_no_second_pass_edit(source: str):
    fixed = fix_text(source)
    assert fix_text(fixed) == fixed


def test_sentence_breaks_depends_on_sentence_classifier_not_other_consumer_views():
    tree = ast.parse(inspect.getsource(sentence_breaks))
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    forbidden_attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    assert "wabun_rst_ulint.checkers._inline_model" not in imported_modules
    assert {"inline", "strong", "decisions", "owners"}.isdisjoint(forbidden_attrs)


def test_sentence_module_uses_public_sentence_breaks_name():
    """Issue #14: sentence checker の公開モジュール名は sentence_breaks である。"""
    import importlib

    module = importlib.import_module("wabun_rst_ulint.checkers.sentence_breaks")
    assert module._logger.name == "wabun_rst_ulint.sentence_breaks"
    assert hasattr(module, "find_violations")
    assert hasattr(module, "fix_text")
    assert hasattr(module, "run")

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("wabun_rst_ulint.checkers.kuten")
