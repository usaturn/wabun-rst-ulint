"""Issue #4 provenance: strong/emphasis interior literals must not be repaired."""

from __future__ import annotations

from tests.inline_corpus.cases import InlineCorpusCase

_ORIGIN = "https://github.com/usaturn/urst-checker/issues/4"


def cases() -> list[InlineCorpusCase]:
    return [
        InlineCorpusCase(
            id="issue4.strong-wrapped-literal.valid",
            source="本文 **``重要``** です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes=(
                "minimal reproduction: valid strong wrapping literal must stay "
                "unchanged; naive `` boundary insert would destroy strong"
            ),
        ),
        InlineCorpusCase(
            id="issue4.strong-wrapped-literal.boundary-deficient",
            source="本文**``重要``**です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes=(
                "boundary-deficient strong+literal: backtick after * is not a "
                "docutils start boundary — do not repair as independent literal"
            ),
        ),
        InlineCorpusCase(
            id="issue4.emphasis-wrapped-literal.valid",
            source="本文 *``重要``* です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="emphasis-wrapped literal control (same family as strong)",
        ),
        InlineCorpusCase(
            id="issue4.outer-strong-boundary.repairable",
            source="本文**a ``code`` b**です\n",
            decision="repairable",
            must_fix=True,
            expected="本文 **a ``code`` b** です\n",
            origin=_ORIGIN,
            notes=(
                "related family: outer strong boundaries may need repair while "
                "interior literal stays intact (also issue #6)"
            ),
        ),
    ]
