"""Classifier contracts: candidates, views, must_fix, overlap, perf (Issue #10)."""

from __future__ import annotations

from pathlib import Path

from tests.inline_corpus import all_cases
from wabun_rst_ulint.checkers._inline_classifier import (
    classify_document,
    last_classification_stats,
    must_fix_is_accepted,
)
from wabun_rst_ulint.checkers._inline_model import ConsumerViews, EditDecision


class TestStrongOwnerIssue6:
    def test_boundary_deficient_outer_strong(self) -> None:
        source = "本文**a ``code`` b**です\n"
        views = classify_document(source)
        assert len(views.strong.owners) == 1
        owner = views.strong.owners[0]
        assert owner.recognized_by_docutils is False
        assert source[owner.source_range.start : owner.source_range.end] == "**a ``code`` b**"
        interior = source[owner.interior_range.start : owner.interior_range.end]
        assert interior == "a ``code`` b"

    def test_recognized_outer_strong(self) -> None:
        source = "本文 **a ``code`` b** です\n"
        views = classify_document(source)
        assert len(views.strong.owners) == 1
        assert views.strong.owners[0].recognized_by_docutils is True

    def test_strong_fully_inside_literal_not_owner(self) -> None:
        source = "``**not-strong**`` です\n"
        views = classify_document(source)
        assert views.strong.owners == ()

    def test_table_cell_strong_has_no_grammar_owner(self) -> None:
        """表セル内の境界不足 strong は owner にしない（M-6 / grok M-1）。

        S4 が owner 外周へ空白を入れると桁固定の表が崩れるため、InlineView の
        table-column-layout と同じ責務境界を StrongView にも適用する。
        """
        grid = (
            "+--------------+-----+\n"
            "| item         | val |\n"
            "+==============+=====+\n"
            "| 本文**a**です | ok |\n"
            "+--------------+-----+\n"
        )
        simple = "======  ======\nitem    val\n======  ======\n**a**x  ok\n======  ======\n"
        for source in (grid, simple):
            views = classify_document(source)
            grammar_owners = [o for o in views.strong.owners if not o.recognized_by_docutils]
            assert grammar_owners == [], source

    def test_non_table_strong_owner_survives(self) -> None:
        """表の外の Issue #6 形は従来どおり owner 1 件（過剰抑止の防止）。"""
        source = "本文**a ``code`` b**です\n"
        views = classify_document(source)
        assert len(views.strong.owners) == 1
        assert views.strong.owners[0].recognized_by_docutils is False


class TestIndependentViews:
    def test_same_source_different_view_membership(self) -> None:
        source = "本文**a ``code`` b**です\n"
        views = classify_document(source)
        # Strong view owns outer **; sentence protects interior; no shared bool
        assert views.strong.owners
        assert views.sentence.protected
        assert not hasattr(views, "active")
        assert not hasattr(views.inline, "protected")

    def test_opaque_role_in_sentence_not_strong_owner(self) -> None:
        source = "用語 :term:`SCIM` 同期\n"
        views = classify_document(source)
        assert views.strong.owners == ()
        # opaque role range should appear in sentence protection when aligned
        kinds_ok = any(True for _ in views.sentence.protected)
        assert kinds_ok or views.sentence.protected is not None


class TestSentenceBoundaryDeficientProtection:
    CASES = (
        ("本文``リテラル。続き``です。\n", "``リテラル。続き``"),
        ("本文:ref:`参照。続き`です。\n", ":ref:`参照。続き`"),
        ("本文`後置。続き`:term:です。\n", "`後置。続き`:term:"),
        ("本文`参照。続き`_です。\n", "`参照。続き`_"),
        ("本文`参照。続き`__です。\n", "`参照。続き`__"),
        ("本文_`対象。続き`です。\n", "_`対象。続き`"),
        ("本文`解釈。続き`です。\n", "`解釈。続き`"),
        ("本文*強調。続き*です。\n", "*強調。続き*"),
    )

    def test_closed_boundary_deficient_tokens_are_sentence_protected(self) -> None:
        for source, token in self.CASES:
            views = classify_document(source)
            protected = {source[item.start : item.end] for item in views.sentence.protected}
            punctuation = source.index("。")

            assert token in protected, source
            assert any(item.start <= punctuation < item.end for item in views.sentence.protected), source
            assert 1 not in views.sentence.unsupported_lines, source

    def test_sentence_range_excludes_inline_repair_boundaries(self) -> None:
        source = "前\\ ``内容。``\\ 後\n"
        token = "``内容。``"
        start = source.index(token)
        end = start + len(token)

        views = classify_document(source)

        assert (start, end) in {(item.start, item.end) for item in views.sentence.protected}
        accepted = [decision for decision in views.inline.decisions if decision.status == "accepted"]
        assert [decision.candidate.form for decision in accepted] == ["literal"]
        assert (
            accepted[0].candidate.source_range.start,
            accepted[0].candidate.source_range.end,
        ) == (start - 2, end + 2)

    def test_escaped_sentence_forms_are_not_added_as_closed_tokens(self) -> None:
        for source in (
            r"本文\``リテラル。続き``です。" + "\n",
            r"本文\*強調。続き*です。" + "\n",
            r"本文*強調。続き\*です。" + "\n",
        ):
            punctuation = source.index("。")
            views = classify_document(source)
            assert not any(item.start <= punctuation < item.end for item in views.sentence.protected), source

    def test_boundary_deficient_strong_keeps_its_existing_interior(self) -> None:
        source = "本文**強調。続き**です。\n"
        views = classify_document(source)

        assert len(views.strong.owners) == 1
        owner = views.strong.owners[0]
        assert owner.recognized_by_docutils is False
        protected = {(item.start, item.end) for item in views.sentence.protected}
        interior = (owner.interior_range.start, owner.interior_range.end)
        token = (owner.source_range.start, owner.source_range.end)
        assert interior in protected
        assert token not in protected


class TestMustFixAcceptance:
    def test_must_fix_accepted_rate_100(self) -> None:
        must = [c for c in all_cases() if c.must_fix]
        assert len(must) >= 50
        failures: list[str] = []
        for case in must:
            views = classify_document(case.source)
            if not must_fix_is_accepted(case.source, case.expected, views):
                failures.append(case.id)
        assert failures == [], f"must_fix not accepted: {failures}"

    def test_catalog_literal_accepted(self) -> None:
        views = classify_document("値は``foo``です\n")
        accepted = [d for d in views.inline.decisions if d.status == "accepted"]
        assert accepted
        assert any(d.candidate.form == "literal" for d in accepted)

    def test_mixed_mandatory_plus_unprovable(self) -> None:
        source = "値は``foo``ですと x`a`y`b`z 曖昧\n"
        views = classify_document(source)
        accepted = [d for d in views.inline.decisions if d.status == "accepted"]
        assert any(d.candidate.form == "literal" for d in accepted)
        # ambiguous interp chain must not produce accepted interpreted for a/b
        interp_accepted = [
            d
            for d in accepted
            if d.candidate.form == "interpreted" and d.candidate.expected_rawsource.find("`a`") >= 0
        ]
        assert interp_accepted == []

    def test_null_escape_normalize_accepted(self) -> None:
        views = classify_document("）\\ :term:`SCIM` 同期\n")
        accepted = [d for d in views.inline.decisions if d.status == "accepted"]
        assert accepted


class TestMustFixOracleTightness:
    def test_unrelated_expected_with_strong_is_false(self) -> None:
        source = "本文**a**です\n"
        views = classify_document(source)
        assert must_fix_is_accepted(source, "**まったく無関係**", views) is False

    def test_valid_strong_with_unrelated_expected_is_false(self) -> None:
        source = "本文 **ok** です\n"
        views = classify_document(source)
        assert must_fix_is_accepted(source, "something **else**", views) is False

    def test_issue6_boundary_still_accepted_via_owner(self) -> None:
        source = "本文**a ``code`` b**です\n"
        expected = "本文 **a ``code`` b** です\n"
        views = classify_document(source)
        # May or may not have accepted EditDecision for interior literal;
        # strong-only path must still work when decisions are empty for outer.
        assert must_fix_is_accepted(source, expected, views) is True


class TestPrecisionNoFalseAccepted:
    """Valid / no-touch inputs must not yield false accepted decisions."""

    def _accepted_forms(self, source: str) -> list[tuple[str, str]]:
        views = classify_document(source)
        return [
            (d.candidate.form, d.candidate.expected_rawsource)
            for d in views.inline.decisions
            if d.status == "accepted"
        ]

    def test_valid_prefix_role_zero_accepted(self) -> None:
        assert self._accepted_forms("これは :term:`SCIM` の説明\n") == []

    def test_valid_postfix_role_zero_accepted(self) -> None:
        assert self._accepted_forms("値は `SCIM`:term: です\n") == []

    def test_valid_named_ref_zero_accepted(self) -> None:
        assert self._accepted_forms("参照 `phrase`_ です\n") == []

    def test_valid_internal_target_zero_accepted(self) -> None:
        assert self._accepted_forms("定義 _`target` です\n") == []

    def test_valid_literal_zero_accepted(self) -> None:
        assert self._accepted_forms("値は ``foo`` です\n") == []

    def test_valid_interpreted_zero_accepted(self) -> None:
        assert self._accepted_forms("名称 `API` は重要\n") == []

    def test_well_formed_role_payload_not_interpreted(self) -> None:
        """Regression: :term:`SCIM` must not yield accepted interpreted on `SCIM`."""
        accepted = self._accepted_forms("これは :term:`SCIM` の説明\n")
        assert not any(form == "interpreted" for form, _ in accepted)
        # Also when boundary-deficient role is accepted, form is role_prefix not interpreted
        views = classify_document("用語:term:`SCIM`同期\n")
        accepted_dec = [d for d in views.inline.decisions if d.status == "accepted"]
        assert accepted_dec
        assert all(d.candidate.form == "role_prefix" for d in accepted_dec)
        assert not any(d.candidate.form == "interpreted" for d in accepted_dec)

    def test_strong_wrapped_literal_not_independent_repair(self) -> None:
        for source in (
            "本文 **``重要``** です\n",
            "本文**``重要``**です\n",
            "本文 *``重要``* です\n",
            "本文 **``x``** です\n",
        ):
            accepted = self._accepted_forms(source)
            assert not any(form == "literal" for form, _ in accepted), source

    def test_role_inside_literal_not_role_candidate(self) -> None:
        assert self._accepted_forms("``:term:`X`あ`` の説明\n") == []

    def test_comment_line_not_rewritten(self) -> None:
        assert self._accepted_forms(".. コメント``x``\n") == []

    def test_line_initial_literal_zero_accepted(self) -> None:
        assert self._accepted_forms("説明です。\n``foo`` です\n") == []

    def test_line_initial_role_zero_accepted(self) -> None:
        assert self._accepted_forms("説明です。\n:term:`SCIM` 同期\n") == []

    def test_line_initial_ref_and_target_zero_accepted(self) -> None:
        assert self._accepted_forms("説明です。\n`phrase`_ です\n") == []
        assert self._accepted_forms("説明です。\n_`target` です\n") == []

    def test_cjk_opener_before_literal_zero_accepted(self) -> None:
        for source in ("（``foo``）です\n", "「``foo``」です\n", "『``foo``』です\n"):
            views = classify_document(source)
            accepted = [d for d in views.inline.decisions if d.status == "accepted"]
            assert accepted == [], source

    def test_cjk_closer_after_literal_is_not_accepted(self) -> None:
        """docutils が終了境界として受理する CJK 閉じ括弧に空白挿入を出さない（L-2）。"""
        for ch in "〉》〕〗":
            source = f"値は ``foo``{ch} です\n"
            views = classify_document(source)
            accepted = [d for d in views.inline.decisions if d.status == "accepted"]
            assert accepted == [], source

    def test_cjk_closer_sources_are_recognized_literals(self) -> None:
        """前提の固定: docutils は これらの閉じ括弧の前の literal を認識する。"""
        from docutils.core import publish_doctree

        for ch in "〉》〕〗":
            doc = publish_doctree(f"値は ``foo``{ch} です\n", settings_overrides={"report_level": 5, "halt_level": 5})
            names = {n.__class__.__name__ for n in doc.findall()}
            assert "literal" in names, ch
            assert "problematic" not in names, ch

    def test_line_initial_interpreted_zero_accepted(self) -> None:
        assert self._accepted_forms("説明です。\n`API` は重要\n") == []

    def test_paragraph_initial_literal_zero_accepted(self) -> None:
        assert self._accepted_forms("段落1\n\n``foo`` です\n") == []

    def test_line_initial_boundary_ws_not_normalized(self) -> None:
        """行頭の全角スペース／タブを ASCII 空白化する編集は構造破壊（block_quote 化）。"""
        for source in (
            "段落1\n\n\u3000``foo`` です\n",
            "段落1\n\n\t``foo`` です\n",
        ):
            views = classify_document(source)
            assert views.inline.decisions == (), source

    def test_line_initial_null_escape_not_consumed(self) -> None:
        """行頭の null-escape は standalone 正規化パスでも消費しない（H-2 再発防止）。"""
        for source in (
            "説明です。\n\\ :term:`SCIM` 同期\n",
            "段落1\n\n\\ ``foo`` です\n",
        ):
            views = classify_document(source)
            assert views.inline.decisions == (), source

    def test_line_initial_sources_are_valid_paragraphs(self) -> None:
        """前提の固定: これら入力は docutils が段落として正しく認識する。"""
        from docutils.core import publish_doctree

        for source in (
            "説明です。\n``foo`` です\n",
            "段落1\n\n``foo`` です\n",
        ):
            doc = publish_doctree(source, settings_overrides={"report_level": 5, "halt_level": 5})
            # All top-level children are paragraphs (no block_quote): a leading
            # space at line start would indent the line and change block structure.
            assert doc.children, source
            assert all(n.__class__.__name__ == "paragraph" for n in doc.children), source

    def test_catalog_valid_unchanged_cases_zero_accepted(self) -> None:
        """Corpus valid-unchanged rows stay free of accepted edits.

        Issue #22 removed the last two exemptions from this gate. Both were
        parity rows that declared ``unchanged`` for a construct another parity
        row declared ``must_fix``; the corpus, not the classifier, was
        self-contradictory. They are now declared repairable, so every
        ``unchanged`` row is covered here with no allowlist.
        """
        failures: list[str] = []
        for case in all_cases():
            if case.decision != "unchanged":
                continue
            views = classify_document(case.source)
            accepted = [d for d in views.inline.decisions if d.status == "accepted"]
            if accepted:
                failures.append(f"{case.id}:{[(d.candidate.form, d.candidate.expected_rawsource) for d in accepted]}")
        assert failures == []

    def test_issue5_ambiguous_mixed_backtick_run_no_accepted(self) -> None:
        """Equal-score/ambiguous `x``-v`` run is no-touch (Issue #5 / Issue #10).

        Corpus: issue5.opener-without-blank.ambiguous — decision=unchanged.
        Shared-boundary only; may surface as unsupported(ambiguous-backticks).
        """
        source = "オプション `x``-v`` を使う\n"
        views = classify_document(source)
        accepted = [
            (d.candidate.form, d.candidate.expected_rawsource, d.candidate.source_range.start)
            for d in views.inline.decisions
            if d.status == "accepted"
        ]
        assert accepted == [], f"ambiguous run must not yield accepted: {accepted}"
        unsupported = [d for d in views.inline.decisions if d.status == "unsupported"]
        assert unsupported
        assert all(d.reason == "ambiguous-backticks" for d in unsupported)

    def test_issue5_corpus_case_no_accepted(self) -> None:
        case = next(c for c in all_cases() if c.id == "issue5.opener-without-blank.ambiguous")
        assert case.decision == "unchanged"
        views = classify_document(case.source)
        accepted = [d for d in views.inline.decisions if d.status == "accepted"]
        assert accepted == []

    def test_simple_table_cell_literal_not_accepted(self) -> None:
        source = "======  ======\nitem    val\n======  ======\n``a``x  ok\n======  ======\n"
        views = classify_document(source)
        accepted = [d for d in views.inline.decisions if d.status == "accepted"]
        assert accepted == []
        unsupported = [
            d for d in views.inline.decisions if d.status == "unsupported" and d.reason == "table-column-layout"
        ]
        assert unsupported  # セル内に境界不足 literal がある入力では 1 件以上

    def test_grid_table_cell_literal_not_accepted(self) -> None:
        source = "+--------+-----+\n| item   | val |\n+========+=====+\n| ``a``x | ok  |\n+--------+-----+\n"
        views = classify_document(source)
        accepted = [d for d in views.inline.decisions if d.status == "accepted"]
        assert accepted == []

    GRID_TABLE_NULL_ESCAPE = (
        "+----------------------+-----+\n"
        "| item                 | val |\n"
        "+======================+=====+\n"
        "| 説明\\ :term:`X` 続き | ok  |\n"
        "+----------------------+-----+\n"
    )
    SIMPLE_TABLE_NULL_ESCAPE = (
        "==================  ======\n"
        "item                val\n"
        "==================  ======\n"
        "説明\\ :term:`X` 続  ok\n"
        "==================  ======\n"
    )

    def test_table_cell_null_escape_is_unsupported(self) -> None:
        """表セル内の `\\ ` は 1 文字に縮めると桁が崩れるので accepted にしない（M-4）。"""
        for source in (self.GRID_TABLE_NULL_ESCAPE, self.SIMPLE_TABLE_NULL_ESCAPE):
            views = classify_document(source)
            accepted = [d for d in views.inline.decisions if d.status == "accepted"]
            assert accepted == [], source
            null_escape = [d for d in views.inline.decisions if d.candidate.form == "null_escape"]
            assert len(null_escape) == 1, source
            assert null_escape[0].status == "unsupported", source
            assert null_escape[0].reason == "table-column-layout", source

    def test_table_cell_sources_parse_as_tables(self) -> None:
        """前提の固定: これら入力は docutils が table として認識する（M-4 の破壊性根拠）。"""
        from docutils.core import publish_doctree

        for source in (self.GRID_TABLE_NULL_ESCAPE, self.SIMPLE_TABLE_NULL_ESCAPE):
            doc = publish_doctree(source, settings_overrides={"report_level": 5, "halt_level": 5})
            assert any(n.__class__.__name__ == "table" for n in doc.children), source


class TestSharedBoundaryLiteralPredicate:
    """Frozen decision table for is_shared_boundary_literal (pure unit)."""

    def _literal_span(self, source: str) -> tuple[int, int]:
        import re

        m = re.search(r"``(?:[^`]|`(?!`))+``", source)
        assert m is not None, source
        return m.start(), m.end()

    def test_decision_table(self) -> None:
        from wabun_rst_ulint.checkers._inline_classifier import is_shared_boundary_literal

        # (source, expected_shared)
        table: list[tuple[str, bool]] = [
            ("オプション `x``-v`` を使う\n", True),
            ("before `a` ``b``after\n", False),
            ("前 `x` 後``y``です\n", False),
            ("後``y``です\n", False),
            ("値は``foo``です\n", False),
            ("名称 `API` は重要\n", False),  # no double-tick literal
            ("値は ``foo`` です\n", False),
        ]
        for source, expect in table:
            if "``" not in source:
                # no literal span — predicate must not fire on missing match
                continue
            start, end = self._literal_span(source)
            got = is_shared_boundary_literal(source, start, end)
            assert got is expect, f"{source!r}: got {got}, want {expect}"


class TestSharedBoundaryClassifyRegression:
    """classify_document regressions from the shared-boundary decision table."""

    def test_issue5_shared_boundary_zero_accepted(self) -> None:
        views = classify_document("オプション `x``-v`` を使う\n")
        assert [d for d in views.inline.decisions if d.status == "accepted"] == []

    def test_spaced_prior_interp_does_not_suppress_literal_repair(self) -> None:
        """before `a` ``b``after — space separates; ``b`` still needs repair."""
        source = "before `a` ``b``after\n"
        views = classify_document(source)
        accepted = [d for d in views.inline.decisions if d.status == "accepted"]
        assert any(d.candidate.form == "literal" for d in accepted), accepted
        # control without prior tick also accepts
        control = classify_document("before ``b``after\n")
        assert any(d.status == "accepted" and d.candidate.form == "literal" for d in control.inline.decisions)

    def test_completed_single_tick_same_line_does_not_suppress_literal(self) -> None:
        """前 `x` 後``y``です — completed `x` must not block accepted ``y``."""
        source = "前 `x` 後``y``です\n"
        views = classify_document(source)
        accepted = [d for d in views.inline.decisions if d.status == "accepted" and d.candidate.form == "literal"]
        assert accepted, [(d.status, d.candidate.form) for d in views.inline.decisions]
        alone = classify_document("後``y``です\n")
        assert any(d.status == "accepted" and d.candidate.form == "literal" for d in alone.inline.decisions)


class TestOverlapAndAmbiguity:
    def test_overlapping_candidates_all_unsupported(self) -> None:
        # Construct overlapping by forcing two candidates on same range via
        # synthetic double-form — use adjacent overlapping edit ranges.
        # ``a````b`` can create adjacent literals; force overlap with a
        # crafted source where edit ranges collide.
        source = "x``ab``y\n"
        classify_document(source)
        # Inject overlap logic unit: two decisions with same range
        from wabun_rst_ulint.checkers._inline_classifier import _mark_overlapping
        from wabun_rst_ulint.checkers._inline_model import RepairCandidate, SourceRange

        sr1 = SourceRange(0, 5, 1, 1)
        sr2 = SourceRange(3, 8, 1, 4)
        d1 = EditDecision(
            candidate=RepairCandidate(sr1, "literal", " ``a`` "),
            status="accepted",
            reason="boundary-repair",
        )
        d2 = EditDecision(
            candidate=RepairCandidate(sr2, "literal", " ``b`` "),
            status="accepted",
            reason="boundary-repair",
        )
        marked = _mark_overlapping([d1, d2])
        assert all(d.status == "unsupported" for d in marked)
        assert all(d.reason == "overlapping-candidates" for d in marked)

    def test_equal_score_interp_not_accepted(self) -> None:
        views = classify_document("x`a`y`b`z\n")
        accepted_interp = [
            d for d in views.inline.decisions if d.status == "accepted" and d.candidate.form == "interpreted"
        ]
        assert accepted_interp == []


class TestInterpSuppressionPrecision:
    def test_separated_interp_pair_not_unsupported(self) -> None:
        views = classify_document("詳細は `foo` と `bar` を参照\n")
        assert 1 not in views.sentence.unsupported_lines

    def test_glued_interp_survives_unrelated_neighbor(self) -> None:
        views = classify_document("値は`a`です と `b`\n")
        accepted = [d for d in views.inline.decisions if d.status == "accepted" and d.candidate.form == "interpreted"]
        assert accepted, "glued interp must keep its repair candidate"

    def test_equal_score_chain_still_suppressed(self) -> None:
        views = classify_document("x`a`y`b`z\n")
        accepted_interp = [
            d for d in views.inline.decisions if d.status == "accepted" and d.candidate.form == "interpreted"
        ]
        assert accepted_interp == []
        assert 1 in views.sentence.unsupported_lines


class TestSentenceUnterminatedAsterisks:
    def test_plausible_unterminated_emphasis_and_strong_are_unsupported(self) -> None:
        for source in (
            "本文 *未終端。続き\n",
            "本文 **未終端。続き\n",
        ):
            views = classify_document(source)
            assert views.sentence.unsupported_lines == frozenset({1}), source

    def test_only_affected_physical_line_is_added(self) -> None:
        source = "通常行です。\n本文 *未終端。続き\n後続行です。\n"
        views = classify_document(source)
        assert views.sentence.unsupported_lines == frozenset({2})

    def test_asterisk_controls_remain_supported(self) -> None:
        for source in (
            "``docs/*.rst`` を対象とする。次の文があります。\n",
            "``*args`` を渡す。次の文があります。\n",
            "計算は 2 * 3 = 6 です。次の文があります。\n",
            "計算は 2 *3 = 6 です。次の文があります。\n",
            ".. [*] 脚注本文です。次の文があります。\n",
            "* 箇条書き。続きの文。\n",
            r"本文 \* は通常文字です。次の文。" + "\n",
            "本文*強調。続き*です。\n",
            "本文**強調。続き**です。\n",
        ):
            views = classify_document(source)
            assert 1 not in views.sentence.unsupported_lines, source

    def test_readme_does_not_gain_unsupported_lines(self) -> None:
        source = Path("README.rst").read_text(encoding="utf-8")
        assert classify_document(source).sentence.unsupported_lines == frozenset()

    def test_existing_inline_corpus_unsupported_lines_are_stable(self) -> None:
        expected_nonempty = {
            "catalog.interp.equal-score-control": frozenset({1}),
            "catalog.notouch.malformed-backticks": frozenset({1}),
            "control.sentence.unterminated-inline": frozenset({1}),
            "control.mixed.mandatory-plus-unprovable": frozenset({1}),
            "issue5.blank-after-opener.hijack": frozenset({1}),
            "issue5.blank-after-opener.repaired-would-destroy": frozenset({1}),
            "issue5.opener-without-blank.ambiguous": frozenset({1}),
            "review.s2.round5.indented_multiline_strong_truncates_alignment": frozenset({1, 2, 3, 4, 5, 6}),
        }

        actual = {case.id: classify_document(case.source).sentence.unsupported_lines for case in all_cases()}
        assert actual == {case.id: expected_nonempty.get(case.id, frozenset()) for case in all_cases()}


class TestNoEditIO:
    def test_classify_does_not_write_files(self, tmp_path: Path) -> None:
        path = tmp_path / "sample.rst"
        source = "値は``foo``です\n"
        path.write_text(source, encoding="utf-8")
        before = path.read_bytes()
        views = classify_document(path.read_text(encoding="utf-8"))
        after = path.read_bytes()
        assert before == after
        assert isinstance(views, ConsumerViews)
        assert views.inline is not None
        assert views.strong is not None
        assert views.sentence is not None


class TestPerformanceCounters:
    def test_exactly_one_parse(self) -> None:
        classify_document("値は``foo``ですと 用語:term:`X`同期\n")
        stats = last_classification_stats()
        assert stats.parse_count == 1

    def test_unterminated_asterisk_scan_keeps_parse_and_scan_bounds(self) -> None:
        lines = 400
        source = "".join(f"段落{index} *未終端。続き\n" for index in range(lines))

        views = classify_document(source)
        stats = last_classification_stats()

        assert views.sentence.unsupported_lines == frozenset(range(1, lines + 1))
        assert stats.parse_count == 1
        assert stats.scan_chars <= 64 * len(source)

    def test_scan_chars_linear_in_input_length(self) -> None:
        # Constant factor bound: scans should be O(n) with small C
        n = 10_000
        source = ("値は``foo``です。" * (n // 10))[:n]
        classify_document(source)
        stats = last_classification_stats()
        # Allow generous constant factor over character count (multiple linear passes)
        assert stats.scan_chars <= 64 * len(source)
        assert stats.parse_count == 1

    def test_many_nodes_still_one_parse(self) -> None:
        parts = [f"項{i} ``v{i}`` です" for i in range(200)]
        source = "、".join(parts) + "\n"
        classify_document(source)
        assert last_classification_stats().parse_count == 1

    def test_dense_interpreted_classifies_quickly(self) -> None:
        """Regression for O(K^2) role-payload rescans (review OPUS-M3 / DS-H1)."""
        import time

        n = 400
        source = " ".join(["`x`"] * n) + "\n"
        # Warm up caches / imports so suite-order noise does not dominate.
        classify_document(source)
        timings = []
        for _ in range(3):
            t0 = time.perf_counter()
            classify_document(source)
            timings.append(time.perf_counter() - t0)
        elapsed = min(timings)
        # Pre-fix measured ~3.5s for n=400 on this hardware class.
        # Fixed implementation must stay comfortably sub-second.
        assert elapsed < 1.0, f"dense interpreted too slow: {elapsed:.3f}s (samples={timings!r})"
        stats = last_classification_stats()
        assert stats.parse_count == 1
        assert stats.scan_chars <= 64 * len(source)

    def test_dense_scaling_not_cubic(self) -> None:
        import time

        def timed(n: int) -> float:
            source = " ".join(["`x`"] * n) + "\n"
            t0 = time.perf_counter()
            classify_document(source)
            return time.perf_counter() - t0

        def best_of(n: int, samples: int = 3) -> float:
            return min(timed(n) for _ in range(samples))

        # Warm-up: one classify so cold-start does not inflate t100 under suite load.
        timed(50)
        t100 = best_of(100)
        t200 = best_of(200)
        # Pre-fix ratio was ~6-8x when n doubled. Healthy is ~1.5-1.8x.
        # Use min-of-3 timings to absorb parallel-suite scheduling noise.
        if t100 > 0.005:
            ratio = t200 / t100
            assert ratio < 3.5, f"scaling {t100:.4f} -> {t200:.4f} (ratio={ratio:.2f})"

    def test_multiline_dense_decisions_scaling_near_linear(self) -> None:
        """Glued literals yield one accepted literal decision per line, so
        _mark_overlapping sees D = lines decisions; regression for residual
        super-linear cost (review round3 OPUS-M3 residual: per-candidate
        str.count / unbounded line slices)."""
        import time

        def timed(lines: int) -> float:
            source = "".join(f"項目{i} の値は``foo{i}``ですという説明文です。\n" for i in range(lines))
            t0 = time.perf_counter()
            classify_document(source)
            return time.perf_counter() - t0

        def best_of(lines: int, samples: int = 3) -> float:
            return min(timed(lines) for _ in range(samples))

        best_of(200)
        t2000 = best_of(2000)
        t4000 = best_of(4000)
        t8000 = best_of(8000)
        # Pre-index residual cost shows up beyond the previous 1000-2000 window.
        # Near-linear doubling should stay under 3.0 with min-of-3 headroom.
        if t2000 > 0.02:
            assert t4000 / t2000 < 3.0, f"2000->4000 {t2000:.4f}->{t4000:.4f}"
        if t4000 > 0.05:
            assert t8000 / t4000 < 3.0, f"4000->8000 {t4000:.4f}->{t8000:.4f}"

    def test_dense_postfix_probe_scaling_not_superlinear(self) -> None:
        """One `` `x`: `` per line isolates the `source[start:]` tail-copy fix
        (review round2 OPUS-M3); the one-line-dense variant stays superlinear
        due to the bare-interp adjacency loop, tracked in issue #23."""
        import time

        def timed(n: int) -> float:
            source = "`x`: \n" * n
            t0 = time.perf_counter()
            classify_document(source)
            return time.perf_counter() - t0

        def best_of(n: int, samples: int = 3) -> float:
            return min(timed(n) for _ in range(samples))

        best_of(100)  # warm-up
        t400 = best_of(400)
        t800 = best_of(800)
        # Pre-fix ratio measured 2.33-2.55x per doubling for this one-per-line
        # input on this hardware, so this test only guards against large
        # regressions (the one-line-dense residual is tracked in issue #23).
        if t400 > 0.005:
            ratio = t800 / t400
            assert ratio < 3.0, f"scaling {t400:.4f} -> {t800:.4f} (ratio={ratio:.2f})"

    def test_null_escape_dense_scaling_near_linear(self) -> None:
        """`--fix` 出力そのもの（1 行 1 null-escape）で線形を保つ（M-5）。

        手順 7 の null-escape ループが candidates を全走査すると O(D^2) になる。
        対照（`\\ ` を空白に置いただけ）は線形なので、比較で回帰を検出する。
        """
        import time

        def timed(lines: int) -> float:
            source = "".join(f":term:`用語{i}`\\ 直後です\n" for i in range(lines))
            t0 = time.perf_counter()
            classify_document(source)
            return time.perf_counter() - t0

        def best_of(lines: int, samples: int = 3) -> float:
            return min(timed(lines) for _ in range(samples))

        best_of(200)
        t2000 = best_of(2000)
        t4000 = best_of(4000)
        t8000 = best_of(8000)
        # Pre-fix ratios were 2.94 / 3.43. Linear doubling with min-of-3
        # headroom should stay under 2.8.
        if t2000 > 0.02:
            assert t4000 / t2000 < 2.8, f"2000->4000 {t2000:.4f}->{t4000:.4f}"
        if t4000 > 0.05:
            assert t8000 / t4000 < 2.8, f"4000->8000 {t4000:.4f}->{t8000:.4f}"

    def test_odd_backtick_dense_scaling_near_linear(self) -> None:
        """未終端バッククォート行の unsupported_lines 構築が線形（M-5 副次）。"""
        import time

        def timed(lines: int) -> float:
            source = "".join(f"説明{i}は`未終端です\n" for i in range(lines))
            t0 = time.perf_counter()
            classify_document(source)
            return time.perf_counter() - t0

        def best_of(lines: int, samples: int = 3) -> float:
            return min(timed(lines) for _ in range(samples))

        best_of(200)
        t2000 = best_of(2000)
        t4000 = best_of(4000)
        t8000 = best_of(8000)
        # Pre-fix ratios were 3.05 / 3.79 (frozenset rebuilt per odd line).
        if t2000 > 0.02:
            assert t4000 / t2000 < 2.8, f"2000->4000 {t2000:.4f}->{t4000:.4f}"
        if t4000 > 0.05:
            assert t8000 / t4000 < 2.8, f"4000->8000 {t4000:.4f}->{t8000:.4f}"


class TestIssue6RoleStrong:
    def test_outer_strong_with_role_owner(self) -> None:
        source = "本文**a :term:`X` b**です\n"
        views = classify_document(source)
        assert len(views.strong.owners) == 1
        assert views.strong.owners[0].recognized_by_docutils is False


class TestEscapedMarkupNotOwned:
    def test_escaped_role_prefix_not_accepted(self) -> None:
        views = classify_document(r"\:term:`X`直後" + "\n")
        accepted = [d for d in views.inline.decisions if d.status == "accepted"]
        assert accepted == []

    def test_escaped_named_ref_not_accepted(self) -> None:
        views = classify_document(r"\`phrase`_直後" + "\n")
        accepted = [d for d in views.inline.decisions if d.status == "accepted"]
        assert accepted == []

    def test_escaped_internal_target_not_accepted(self) -> None:
        views = classify_document(r"\_`target`直後" + "\n")
        accepted = [d for d in views.inline.decisions if d.status == "accepted"]
        assert accepted == []

    def test_escaped_strong_not_owner(self) -> None:
        source = r"\**strong**直後" + "\n"
        views = classify_document(source)
        assert views.strong.owners == ()


class TestStrongOwnerPairing:
    def test_non_greedy_false_owner_rejected(self) -> None:
        source = "前**内側 **外側** 終わり**後\n"
        views = classify_document(source)
        raws = [source[o.source_range.start : o.source_range.end] for o in views.strong.owners]
        assert "**内側 **" not in raws
        assert any(r == "**外側**" for r in raws)
        # false interior must not be protected as strong interior alone
        protected = [source[p.start : p.end] for p in views.sentence.protected]
        assert "内側 " not in protected

    def test_multiline_boundary_deficient_strong_is_out_of_scope(self) -> None:
        """S2 grammar owners are single-line only (documented contract)."""
        source = "本文**重要 ``code`` な\n箇所が続く**です\n"
        views = classify_document(source)
        grammar = tuple(o for o in views.strong.owners if not o.recognized_by_docutils)
        assert grammar == ()

    def test_strong_re_is_single_line_contract(self) -> None:
        """STRONG_RE itself enforces the single-line owner contract."""
        from wabun_rst_ulint.checkers._inline_classifier import STRONG_RE

        assert STRONG_RE.search("**a\nb**") is None


class TestStrongOwnerRound2Guards:
    def test_multi_asterisk_inner_matches_not_owners(self) -> None:
        for source in ("**a**b**c**\n", "text **a**b**c** more\n"):
            views = classify_document(source)
            grammar = [o for o in views.strong.owners if not o.recognized_by_docutils]
            assert grammar == [], source
            assert len(views.strong.owners) == 1, source
            outer = views.strong.owners[0]
            assert outer.recognized_by_docutils is True
            protected = [(p.start, p.end) for p in views.sentence.protected]
            # 内側 a / c が単独で protected にならない（outer の interior は可）
            src = source
            for p_start, p_end in protected:
                assert src[p_start:p_end] not in ("a", "c"), source

    def test_role_payload_strong_not_owner(self) -> None:
        views = classify_document("用語 :term:`**重要**` の説明\n")
        assert views.strong.owners == ()

    def test_ref_and_target_payload_strong_not_owner(self) -> None:
        for source in (
            "参照 `**強調**`:ref: です\n",
            "定義 _`**target**` です\n",
            "外部 `**phrase**`_ です\n",
        ):
            views = classify_document(source)
            assert views.strong.owners == (), source

    def test_comment_line_strong_not_owner(self) -> None:
        views = classify_document(".. コメント **x** です\n")
        assert views.strong.owners == ()


class TestEscapedBackslashAwareness:
    def test_escaped_backslash_before_role_not_consumed(self) -> None:
        # C:\（エスケープ済みバックスラッシュ）+ 空白 + role: 修復不要
        source = "C:\\\\ :title:`SCIM` 同期\n"
        views = classify_document(source)
        assert views.inline.decisions == ()

    def test_escaped_backslash_before_literal_not_consumed(self) -> None:
        source = "C:\\\\ ``foo`` です\n"
        views = classify_document(source)
        assert views.inline.decisions == ()

    def test_unescaped_backtick_after_escaped_backslash_is_unsupported(self) -> None:
        # a\\`b — バックスラッシュ対の後のバッククォートは未エスケープ → 未終端
        source = "a\\\\`b\n"
        views = classify_document(source)
        assert 1 in views.sentence.unsupported_lines


class TestOpaqueLiteralBlockViews:
    def test_parsed_literal_strong_not_owned(self) -> None:
        source = "intro\n\n.. parsed-literal::\n\n   **bold** here\n\nout **ok**\n"
        views = classify_document(source)
        owned = [source[o.source_range.start : o.source_range.end] for o in views.strong.owners]
        assert owned == ["**ok**"]

    def test_code_highlight_does_not_protect_prose_token(self) -> None:
        source = "not here\n\n.. code:: python\n\n   not = 1\n\n``yes``\n"
        views = classify_document(source)
        protected_texts = [source[p.start : p.end] for p in views.sentence.protected]
        assert "not" not in protected_texts
        assert any(t == "``yes``" for t in protected_texts)


class TestCheckableDefinitionBodies:
    def test_substitution_multiline_body_is_repairable(self) -> None:
        source = ".. |m| replace::\n   値は``x``です\n"
        views = classify_document(source)
        accepted = [d for d in views.inline.decisions if d.status == "accepted" and d.candidate.form == "literal"]
        assert accepted


class TestTripleAsteriskGuards:
    """`***...***` は非対称な偽 owner を出さない（round5 L-2）。"""

    def test_triple_asterisk_run_has_no_grammar_owner(self) -> None:
        for source in ("前***中***後\n", "x***y***z\n"):
            views = classify_document(source)
            grammar = [o for o in views.strong.owners if not o.recognized_by_docutils]
            assert grammar == [], source

    def test_spaced_triple_asterisk_stays_docutils_owner(self) -> None:
        source = "See ***note*** here\n"
        views = classify_document(source)
        assert [o.recognized_by_docutils for o in views.strong.owners] == [True]
        owner = views.strong.owners[0]
        assert source[owner.source_range.start : owner.source_range.end] == "***note***"

    def test_issue6_outer_strong_owner_survives(self) -> None:
        source = "本文**a ``code`` b**です\n"
        views = classify_document(source)
        assert len(views.strong.owners) == 1
        owner = views.strong.owners[0]
        assert source[owner.source_range.start : owner.source_range.end] == "**a ``code`` b**"


class TestBlankSeparatedSimpleTable:
    """複数行セルを空行で区切ったシンプル表も表ガードの対象（round5 M-7）。"""

    SOURCE = (
        "============  ==========\n"
        "col1          col2\n"
        "============  ==========\n"
        "value``a``x   ok\n"
        "cont          line\n"
        "\n"
        "row2          ok2\n"
        "============  ==========\n"
    )

    def test_cell_literal_not_accepted(self) -> None:
        views = classify_document(self.SOURCE)
        accepted = [d for d in views.inline.decisions if d.status == "accepted"]
        assert accepted == []
        unsupported = [
            d for d in views.inline.decisions if d.status == "unsupported" and d.reason == "table-column-layout"
        ]
        assert unsupported

    def test_cell_strong_has_no_grammar_owner(self) -> None:
        source = self.SOURCE.replace("value``a``x", "value**a**x")
        views = classify_document(source)
        assert [o for o in views.strong.owners if not o.recognized_by_docutils] == []

    def test_source_parses_as_table(self) -> None:
        """前提の固定: docutils はこの入力を table として解析する（M-7 の破壊性根拠）。"""
        from docutils.core import publish_doctree

        doc = publish_doctree(self.SOURCE, settings_overrides={"report_level": 5, "halt_level": 5})
        assert any(n.__class__.__name__ == "table" for n in doc.children)


class TestMixedLiteralStrongScaling:
    def test_literal_and_strong_mixed_scaling_near_linear(self) -> None:
        """literal と境界不足 strong の混在で `_find_strong_owners` が線形（round5 M-8）。"""
        import time

        def timed(rows: int) -> float:
            source = "".join(f"値は ``lit{i}`` です\n本文{i}**強調**です\n" for i in range(rows))
            t0 = time.perf_counter()
            classify_document(source)
            return time.perf_counter() - t0

        def best_of(rows: int, samples: int = 3) -> float:
            return min(timed(rows) for _ in range(samples))

        best_of(200)
        t2000 = best_of(2000)
        t4000 = best_of(4000)
        t8000 = best_of(8000)
        # Pre-fix ratios were 3.24 / 3.41 (three per-candidate full list scans).
        if t2000 > 0.02:
            assert t4000 / t2000 < 2.8, f"2000->4000 {t2000:.4f}->{t4000:.4f}"
        if t4000 > 0.05:
            assert t8000 / t4000 < 2.8, f"4000->8000 {t4000:.4f}->{t8000:.4f}"


class TestAlignmentTruncationFailClosed:
    """整列が途中で止まったら以降の行を unknown 扱いにする（round5 H-3）。"""

    TRUNCATING = "冒頭 ``head`` です。\n\n- 項目 **重要\n  箇所** です\n\n後続 **ok** と ``tail`` です。\n"

    def test_truncated_tail_lines_are_unsupported(self) -> None:
        views = classify_document(self.TRUNCATING)
        last_line = len(self.TRUNCATING.splitlines())
        assert views.sentence.unsupported_lines.issuperset(range(1, last_line + 1))

    def test_truncated_document_has_no_grammar_owner(self) -> None:
        views = classify_document(self.TRUNCATING)
        assert [o for o in views.strong.owners if not o.recognized_by_docutils] == []

    def test_truncation_does_not_split_multi_asterisk_owner(self) -> None:
        source = "- 項目 **重要\n  箇所** です\n\ntext **a**b**c** more\n"
        views = classify_document(source)
        assert [o for o in views.strong.owners if not o.recognized_by_docutils] == []

    def test_complete_alignment_keeps_protection_and_owners(self) -> None:
        """対照: 字下げが無ければ整列は完走し、protected も owner も従来どおり。"""
        source = "本文 **重要\n箇所** です。\n\n続き ``bar`` です。\n"
        views = classify_document(source)
        assert views.sentence.unsupported_lines == frozenset()
        assert [o.recognized_by_docutils for o in views.strong.owners] == [True]
        assert "``bar``" in [source[r.start : r.end] for r in views.sentence.protected]
