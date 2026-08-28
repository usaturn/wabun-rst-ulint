"""Round-4 review regression cases for S2 classifier."""

from __future__ import annotations

from tests.inline_corpus.cases import InlineCorpusCase

_ORIGIN = "https://github.com/usaturn/urst-checker/pull/20"


def cases() -> list[InlineCorpusCase]:
    return [
        InlineCorpusCase(
            id="review.s2.round4.grid_table_cell_null_escape",
            source=(
                "+----------------------+-----+\n"
                "| item                 | val |\n"
                "+======================+=====+\n"
                "| 説明\\ :term:`X` 続き | ok  |\n"
                "+----------------------+-----+\n"
            ),
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="grid-table cell: `\\ ` -> ' ' would shrink the column (table-column-layout)",
        ),
        InlineCorpusCase(
            id="review.s2.round4.simple_table_cell_null_escape",
            source=(
                "==================  ======\n"
                "item                val\n"
                "==================  ======\n"
                "説明\\ :term:`X` 続  ok\n"
                "==================  ======\n"
            ),
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="simple-table cell: same column-shrink hazard as the grid form",
        ),
        InlineCorpusCase(
            id="review.s2.round4.simple_table_cell_strong",
            source="======  ======\nitem    val\n======  ======\n**a**x  ok\n======  ======\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="simple-table cell: no grammar StrongOwner, S4 must not widen the cell",
        ),
        InlineCorpusCase(
            id="review.s2.round4.grid_table_cell_strong",
            source=(
                "+--------------+-----+\n"
                "| item         | val |\n"
                "+==============+=====+\n"
                "| 本文**a**です | ok |\n"
                "+--------------+-----+\n"
            ),
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="grid-table cell: no grammar StrongOwner",
        ),
        InlineCorpusCase(
            id="review.s2.round4.cjk_closer_angle_literal",
            source="値は ``foo``〉です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="CJK closer is a legal docutils end boundary; no after-space repair",
        ),
        InlineCorpusCase(
            id="review.s2.round4.cjk_closer_double_angle_literal",
            source="値は ``foo``》です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="CJK double angle closer; pairs with 《 in _LITERAL_OK_BEFORE",
        ),
    ]
