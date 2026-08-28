"""PR #3 review categories transcribed with PR URL provenance (not reviews/)."""

from __future__ import annotations

from tests.inline_corpus.cases import InlineCorpusCase

_ORIGIN = "https://github.com/usaturn/urst-checker/pull/3"


def cases() -> list[InlineCorpusCase]:
    return [
        InlineCorpusCase(
            id="review.pr3.csv-table-body-skipped",
            source=".. csv-table::\n\n   名前,``値``\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="review: csv-table body excluded from inline-spacing edits",
        ),
        InlineCorpusCase(
            id="review.pr3.list-marker-preserved",
            source="- 項目``x``です\n",
            decision="repairable",
            must_fix=True,
            expected="- 項目 ``x`` です\n",
            origin=_ORIGIN,
            notes="review: list marker preserved while content boundaries repair",
        ),
        InlineCorpusCase(
            id="review.pr3.field-list-marker",
            source=":Name: 値は``x``です\n",
            decision="repairable",
            must_fix=True,
            expected=":Name: 値は ``x`` です\n",
            origin=_ORIGIN,
            notes="review: field list marker preserved",
        ),
        InlineCorpusCase(
            id="review.pr3.line-block-prefix",
            source="| 行は``x``です\n",
            decision="repairable",
            must_fix=True,
            expected="| 行は ``x`` です\n",
            origin=_ORIGIN,
            notes="review: line-block prefix preserved",
        ),
        InlineCorpusCase(
            id="review.pr3.doctest-prefix",
            source=">>> print(``x``)\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="review: doctest line structural prefix — no-touch body convention",
        ),
        InlineCorpusCase(
            id="review.pr3.comment-line",
            source=".. コメント``x``\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="review: comment line not rewritten",
        ),
        InlineCorpusCase(
            id="review.pr3.escaped-token-reserved",
            source="表示は\\``raw\\``です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="review: escaped complete token shapes reserved before active repair",
        ),
        InlineCorpusCase(
            id="review.pr3.trailing-nbsp-no-eol-space",
            source="値は ``foo``\u00a0\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo``\n",
            origin=_ORIGIN,
            notes="review: trailing NBSP after token removed without creating EOL ASCII space run",
        ),
        InlineCorpusCase(
            id="review.pr3.tab-normalizes-not-eol-pad",
            source="値は``foo``\t\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo``\n",
            origin=_ORIGIN,
            notes="review: tab normalizes; do not invent trailing halfwidth padding",
        ),
        InlineCorpusCase(
            id="review.pr3.idempotent-single-pass",
            source="値は``foo``です\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo`` です\n",
            origin=_ORIGIN,
            notes="review: fix converges in one pass; second pass is no-op (S3 proves)",
        ),
        InlineCorpusCase(
            id="review.pr3.footnote-checkable",
            source=".. [1] 脚注``x``本文\n",
            decision="repairable",
            must_fix=True,
            expected=".. [1] 脚注 ``x`` 本文\n",
            origin=_ORIGIN,
            notes="review: footnote definition text checkable",
        ),
        InlineCorpusCase(
            id="review.pr3.substitution-checkable",
            source=".. |m| replace:: x:term:`Y`z\n",
            decision="repairable",
            must_fix=True,
            expected=".. |m| replace:: x :term:`Y` z\n",
            origin=_ORIGIN,
            notes="review: substitution definition body checkable",
        ),
    ]
