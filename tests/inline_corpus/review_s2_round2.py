"""PR #20 S2 review round-2 regressions (valid line-initial forms)."""

from __future__ import annotations

from tests.inline_corpus.cases import InlineCorpusCase

_ORIGIN = "https://github.com/usaturn/urst-checker/pull/20"


def cases() -> list[InlineCorpusCase]:
    return [
        InlineCorpusCase(
            id="review.pr20.r2.line-initial.literal.valid-unchanged",
            source="説明です。\n``foo`` です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="round2 H-2/H-1: line-initial literal is a valid boundary",
        ),
        InlineCorpusCase(
            id="review.pr20.r2.line-initial.role.valid-unchanged",
            source="説明です。\n:term:`SCIM` 同期\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="round2 H-2/H-1: line-initial role is a valid boundary",
        ),
        InlineCorpusCase(
            id="review.pr20.r2.line-initial.ref.valid-unchanged",
            source="説明です。\n`phrase`_ です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="round2 H-2/H-1: line-initial named ref is a valid boundary",
        ),
        InlineCorpusCase(
            id="review.pr20.r2.paragraph-initial.boundary-ws.valid-unchanged",
            source="段落1\n\n\u3000``foo`` です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="round2: line-initial ideographic space must not normalize to ASCII",
        ),
    ]
