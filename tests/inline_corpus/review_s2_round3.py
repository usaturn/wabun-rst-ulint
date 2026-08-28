"""Round-3 review regression cases for S2 classifier."""

from __future__ import annotations

from tests.inline_corpus.cases import InlineCorpusCase

_ORIGIN = "https://github.com/usaturn/urst-checker/pull/20"


def cases() -> list[InlineCorpusCase]:
    return [
        InlineCorpusCase(
            id="review.s2.round3.cjk_opener_paren_literal",
            source="（``foo``）です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="CJK opener is a legal docutils boundary; no before-space repair",
        ),
        InlineCorpusCase(
            id="review.s2.round3.cjk_opener_corner_literal",
            source="「``foo``」です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="CJK corner bracket opener",
        ),
        InlineCorpusCase(
            id="review.s2.round3.simple_table_cell_literal",
            source=("======  ======\nitem    val\n======  ======\n``a``x  ok\n======  ======\n"),
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="simple-table cell: boundary repair unsupported (table-column-layout)",
        ),
        InlineCorpusCase(
            id="review.s2.round3.grid_table_cell_literal",
            source=("+--------+-----+\n| item   | val |\n+========+=====+\n| ``a``x | ok  |\n+--------+-----+\n"),
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="grid-table cell: boundary repair unsupported (table-column-layout)",
        ),
    ]
