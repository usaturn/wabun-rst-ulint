"""Issue #5 provenance: blank-after-opener must not hijack a later literal."""

from __future__ import annotations

from tests.inline_corpus.cases import InlineCorpusCase

_ORIGIN = "https://github.com/usaturn/urst-checker/issues/5"


def cases() -> list[InlineCorpusCase]:
    return [
        InlineCorpusCase(
            id="issue5.blank-after-opener.hijack",
            source="オプション ` ``-v`` を使う\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes=(
                "minimal reproduction: valid RST; opener followed by whitespace "
                "must not steal the closer of the following literal"
            ),
        ),
        InlineCorpusCase(
            id="issue5.blank-after-opener.repaired-would-destroy",
            source="オプション ` ``-v`` を使う\n",
            decision="diagnostic-only",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes=(
                "contract: a repair that yields 'オプション ` `` -v`` を使う' is "
                "forbidden; if a tool proposes it, treat as failed/diagnostic, not success"
            ),
        ),
        InlineCorpusCase(
            id="issue5.adjacent-valid-literal.unchanged",
            source="オプション ``-v`` を使う\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="control: plain valid literal without stray opener",
        ),
        InlineCorpusCase(
            id="issue5.opener-without-blank.ambiguous",
            source="オプション `x``-v`` を使う\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=_ORIGIN,
            notes="ambiguous backtick run — no-touch equal-score family control",
        ),
    ]
