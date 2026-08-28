"""Round-5 review regression cases for S2 classifier."""

from __future__ import annotations

from tests.inline_corpus.cases import InlineCorpusCase

_ORIGIN = "https://github.com/usaturn/urst-checker/pull/20"


def cases() -> list[InlineCorpusCase]:
    return [
        InlineCorpusCase(
            id="review.s2.round5.triple_asterisk_run",
            source="前***中***後\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="`***x***` is out of the S2 strong grammar: an asymmetric owner would break markup",
        ),
        InlineCorpusCase(
            id="review.s2.round5.blank_separated_simple_table",
            source=(
                "============  ==========\n"
                "col1          col2\n"
                "============  ==========\n"
                "value``a``x   ok\n"
                "cont          line\n"
                "\n"
                "row2          ok2\n"
                "============  ==========\n"
            ),
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="simple table whose multi-line rows are separated by a blank line (table-column-layout)",
        ),
        InlineCorpusCase(
            id="review.s2.round5.indented_multiline_strong_truncates_alignment",
            source="冒頭 ``head`` です。\n\n- 項目 **重要\n  箇所** です\n\n後続 **ok** と ``tail`` です。\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="indented line-spanning strong truncates alignment; downstream lines must fail closed",
        ),
    ]
