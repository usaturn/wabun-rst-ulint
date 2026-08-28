"""Issue #6 provenance: outer strong with protected interior must still check boundaries."""

from __future__ import annotations

from tests.inline_corpus.cases import InlineCorpusCase

_ORIGIN = "https://github.com/usaturn/urst-checker/issues/6"


def cases() -> list[InlineCorpusCase]:
    return [
        InlineCorpusCase(
            id="issue6.outer-strong-with-literal.missing-boundaries",
            source="本文**a ``code`` b**です\n",
            decision="repairable",
            must_fix=True,
            expected="本文 **a ``code`` b** です\n",
            origin=_ORIGIN,
            notes=(
                "minimal reproduction: protected interior literal must not suppress "
                "outer strong boundary detection/repair"
            ),
        ),
        InlineCorpusCase(
            id="issue6.outer-strong-with-literal.valid",
            source="本文 **a ``code`` b** です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="valid outer strong with interior literal",
        ),
        InlineCorpusCase(
            id="issue6.strong-fully-inside-literal.skip",
            source="``**not-strong**`` です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="strong markers fully inside literal — not an outer strong owner",
        ),
        InlineCorpusCase(
            id="issue6.outer-strong-with-role.missing-boundaries",
            source="本文**a :term:`X` b**です\n",
            decision="repairable",
            must_fix=True,
            expected="本文 **a :term:`X` b** です\n",
            origin=_ORIGIN,
            notes="outer strong with interior role; same outer-owner rule",
        ),
    ]
