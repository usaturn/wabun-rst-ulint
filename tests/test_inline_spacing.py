"""tests for wabun_rst_ulint.checkers.inline_spacing (Issue #11 / S3)."""

from __future__ import annotations

import resource
import signal
from collections import Counter
from dataclasses import replace

import pytest

from tests.inline_corpus import all_cases
from wabun_rst_ulint.checkers import _checker_runner, inline_spacing
from wabun_rst_ulint.checkers._inline_classifier import classify_document
from wabun_rst_ulint.checkers._inline_model import EditDecision, RepairCandidate, SourceRange
from wabun_rst_ulint.checkers._rst_oracle import parse_document
from wabun_rst_ulint.reporting import Violation


class TestMessageNormalization:
    def test_strips_source_line_and_level_wrapper(self):
        body = '<string>:2: (WARNING/2) Duplicate explicit target name: "foo".'
        assert inline_spacing.normalize_message_body(body) == 'Duplicate explicit target name: "foo".'

    def test_collapses_whitespace(self):
        assert inline_spacing.normalize_message_body("  foo   bar  \n baz ") == "foo bar baz"

    def test_messages_counter_counts_duplicate_target(self):
        source = ".. _foo: http://example.com\n.. _foo: http://example.org\n"
        document = parse_document(source).document
        counter = inline_spacing.messages_counter(document)
        assert sum(counter.values()) == 1
        (key,) = counter.keys()
        level, msg_type, body = key
        assert level == 2
        assert msg_type == "WARNING"
        assert body == 'Duplicate explicit target name: "foo".'

    def test_messages_counter_empty_for_clean_document(self):
        document = parse_document("値は ``foo`` です\n").document
        assert inline_spacing.messages_counter(document) == Counter()

    def test_existing_title_warning_body_is_normalized(self):
        # 許可された境界空白差（accepted decision の現状/期待 slice）だけを alias し、
        # 同一タイトルの title-length warning が同じ key になることを確認する。
        before = parse_document("設定は``True``\n==========\n").document
        after = parse_document("設定は ``True``\n==========\n").document
        aliases = (("``True``", "``True``"), (" ``True``", "``True``"))
        assert inline_spacing.messages_counter(before, message_aliases=aliases) == inline_spacing.messages_counter(
            after, message_aliases=aliases
        )


class TestDocumentFingerprint:
    def test_blocks_exclude_system_message_and_its_descendants(self):
        # baseline: docutils が problematic ノード + system_message を生成するケース。
        # system_message は内部に paragraph を持つため、これを block 種別列に含めると
        # 修正で message が消えるたびに block 列が変化し正当な修正を誤検知してしまう。
        source = "用語:term:`SCIM`同期\n"
        fp = inline_spacing.build_document_fingerprint(source)
        assert fp.blocks == ("paragraph",)

    def test_untouched_inlines_excludes_nodes_inside_edit_ranges(self):
        source = "前 ``a`` 中``b``後\n"
        # "``b``" は index 8 から始まる（"前 ``a`` 中" = 8 文字）
        edit_start = source.index("``b``")
        edit_end = edit_start + len("``b``")
        fp = inline_spacing.build_document_fingerprint(source, edit_ranges=((edit_start, edit_end),))
        # "``a``" は編集区間の外なので untouched に残る。"``b``" は除外される。
        assert fp.untouched_inlines == (("literal", "``a``", "a"),)

    def test_untouched_inlines_default_includes_everything(self):
        source = "値は ``foo`` です\n"
        fp = inline_spacing.build_document_fingerprint(source)
        assert fp.untouched_inlines == (("literal", "``foo``", "foo"),)

    def test_named_embedded_uri_target_does_not_truncate_alignment(self):
        source = "詳細は `example <http://example.com>`_ を参照\n"
        fp = inline_spacing.build_document_fingerprint(source)
        assert fp.truncated_from_line is None
        assert fp.untouched_inlines == (("reference", "`example <http://example.com>`_", "example"),)

    def test_unrelated_alignment_failure_still_truncates(self, monkeypatch):
        real_parse = inline_spacing.parse_document
        source = "値は ``foo`` です\n"
        oracle = real_parse(source)
        broken = replace(oracle.inlines[0], rawsource="")
        monkeypatch.setattr(
            inline_spacing,
            "parse_document",
            lambda _source: replace(oracle, inlines=(broken,)),
        )
        fp = inline_spacing.build_document_fingerprint(source)
        assert fp.truncated_from_line is not None

    def test_messages_populated_on_fingerprint(self):
        source = ".. _foo: http://example.com\n.. _foo: http://example.org\n"
        fp = inline_spacing.build_document_fingerprint(source)
        assert sum(fp.messages.values()) == 1

    def test_repeated_identical_literals_keep_multiplicity(self):
        fp = inline_spacing.build_document_fingerprint("``a`` ``a``\n")
        assert fp.truncated_from_line is None
        assert fp.untouched_inlines == (
            ("literal", "``a``", "a"),
            ("literal", "``a``", "a"),
        )

    def test_substitution_image_nodes_keep_definition_and_use_multiplicity(self):
        one_use = inline_spacing.build_document_fingerprint(".. |img| image:: a.png\n\n|img|\n")
        two_uses = inline_spacing.build_document_fingerprint(".. |img| image:: a.png\n\n|img| と |img|\n")
        image = ("image", "image:: a.png", "img")
        assert one_use.truncated_from_line is None
        assert two_uses.truncated_from_line is None
        assert one_use.untouched_inlines == (image, image)
        assert two_uses.untouched_inlines == (image, image, image)
        assert inline_spacing.prove_combined_projection(one_use, two_uses).ok is False

    def test_distinct_substitution_images_do_not_truncate_alignment(self):
        source = ".. |a| image:: a.png\n.. |b| image:: b.png\n\n|a| と |b|\n"
        fp = inline_spacing.build_document_fingerprint(source)
        assert fp.truncated_from_line is None
        assert fp.untouched_inlines == (
            ("image", "image:: a.png", "a"),
            ("image", "image:: b.png", "b"),
            ("image", "image:: a.png", "a"),
            ("image", "image:: b.png", "b"),
        )


def _decision(start: int, end: int, expected: str, *, form: str = "literal", line: int = 1) -> EditDecision:
    return EditDecision(
        candidate=RepairCandidate(
            source_range=SourceRange(start=start, end=end, line=line, column=start + 1),
            form=form,
            expected_rawsource=expected,
        ),
        status="accepted",
        reason="boundary-repair",
    )


class TestAcceptedDecisions:
    def test_filters_to_accepted_only(self):
        accepted = _decision(0, 3, "x")
        rejected = EditDecision(
            candidate=accepted.candidate,
            status="rejected",
            reason="escaped",
        )
        unsupported = EditDecision(
            candidate=accepted.candidate,
            status="unsupported",
            reason="overlapping-candidates",
        )
        result = inline_spacing.accepted_decisions((accepted, rejected, unsupported))
        assert result == (accepted,)


class TestApplyAcceptedEdits:
    def test_empty_decisions_returns_source_unchanged(self):
        plan = inline_spacing.apply_accepted_edits("値は ``foo`` です\n", ())
        assert plan.text == "値は ``foo`` です\n"
        assert plan.original_ranges == ()
        assert plan.projected_ranges == ()

    def test_single_decision_replaces_range(self):
        source = "値は``foo``です\n"
        start = source.index("``foo``")
        end = start + len("``foo``")
        decisions = (_decision(start, end, " ``foo`` "),)
        plan = inline_spacing.apply_accepted_edits(source, decisions)
        assert plan.text == "値は ``foo`` です\n"
        assert plan.original_ranges == ((start, end),)

    def test_two_non_adjacent_decisions_ordering(self):
        source = "前``a``中:term:`B`後\n"
        a_start = source.index("``a``")
        a_end = a_start + len("``a``")
        b_start = source.index(":term:`B`")
        b_end = b_start + len(":term:`B`")
        decisions = (
            _decision(b_start, b_end, " :term:`B` ", form="role_prefix"),
            _decision(a_start, a_end, " ``a`` "),
        )
        plan = inline_spacing.apply_accepted_edits(source, decisions)
        assert plan.text == "前 ``a`` 中 :term:`B` 後\n"
        assert plan.forms == ("literal", "role_prefix")

    def test_adjacent_decisions_collapse_shared_boundary_space(self):
        # S2 は :ref:`a` と :ref:`b` それぞれに独立した accepted decision を出す
        # （前者は後方境界、後者は前方境界）。素朴に連結すると2連スペースになるが、
        # 期待される正規形は1スペースのみ（parity.role_visible_spacing.test_adjacent_roles_single_insert）。
        source = ":ref:`a`:ref:`b` です\n"
        decisions = (
            _decision(0, 8, ":ref:`a` "),
            _decision(8, 16, " :ref:`b`"),
        )
        plan = inline_spacing.apply_accepted_edits(source, decisions)
        assert plan.text == ":ref:`a` :ref:`b` です\n"

    def test_overlapping_decisions_raise(self):
        decisions = (_decision(0, 5, "aaaaa"), _decision(3, 8, "bbbbb"))
        with pytest.raises(inline_spacing.OverlappingEditsError):
            inline_spacing.apply_accepted_edits("0123456789\n", decisions)


def _fingerprint(
    *,
    untouched=(),
    blocks=("paragraph",),
    messages=None,
    truncated_from_line=None,
):
    return inline_spacing.DocumentFingerprint(
        untouched_inlines=untouched,
        blocks=blocks,
        messages=messages if messages is not None else Counter(),
        truncated_from_line=truncated_from_line,
    )


class TestProveCombinedProjection:
    def test_identical_fingerprints_pass(self):
        base = _fingerprint(untouched=(("literal", "``a``", "a"),))
        proj = _fingerprint(untouched=(("literal", "``a``", "a"),))
        result = inline_spacing.prove_combined_projection(base, proj)
        assert result.ok is True
        assert result.reason is None

    def test_untouched_inline_mismatch_fails(self):
        base = _fingerprint(untouched=(("literal", "``a``", "a"),))
        proj = _fingerprint(untouched=(("literal", "``a-corrupted``", "a-corrupted"),))
        result = inline_spacing.prove_combined_projection(base, proj)
        assert result.ok is False
        assert result.reason is not None

    def test_untouched_inline_reordered_fails(self):
        base = _fingerprint(untouched=(("literal", "``a``", "a"), ("literal", "``b``", "b")))
        proj = _fingerprint(untouched=(("literal", "``b``", "b"), ("literal", "``a``", "a")))
        result = inline_spacing.prove_combined_projection(base, proj)
        assert result.ok is False

    def test_block_structure_mismatch_fails(self):
        base = _fingerprint(blocks=("paragraph",))
        proj = _fingerprint(blocks=("paragraph", "bullet_list"))
        result = inline_spacing.prove_combined_projection(base, proj)
        assert result.ok is False
        assert "block" in result.reason

    def test_message_count_increase_fails(self):
        base = _fingerprint(messages=Counter())
        proj = _fingerprint(messages=Counter({(2, "WARNING", "new problem"): 1}))
        result = inline_spacing.prove_combined_projection(base, proj)
        assert result.ok is False
        assert "message" in result.reason

    def test_message_count_decrease_passes(self):
        # 既存 message の消滅は許可する（Issue #11: 同一 key の件数増加を拒否し、消滅は許可）
        base = _fingerprint(messages=Counter({(2, "WARNING", "old problem"): 1}))
        proj = _fingerprint(messages=Counter())
        result = inline_spacing.prove_combined_projection(base, proj)
        assert result.ok is True

    def test_truncated_alignment_on_baseline_fails_closed(self):
        base = _fingerprint(truncated_from_line=2)
        proj = _fingerprint()
        result = inline_spacing.prove_combined_projection(base, proj)
        assert result.ok is False

    def test_truncated_alignment_on_projected_fails_closed(self):
        base = _fingerprint()
        proj = _fingerprint(truncated_from_line=3)
        result = inline_spacing.prove_combined_projection(base, proj)
        assert result.ok is False


class TestCheckDocument:
    def test_no_violations_for_valid_source(self):
        result = inline_spacing.check_document("値は ``foo`` です\n")
        assert result.violations == ()

    def test_reports_accepted_candidate_as_violation(self):
        result = inline_spacing.check_document("値は``foo``です\n")
        assert len(result.violations) == 1
        assert result.violations[0].kind == "literal"

    def test_reports_trailing_whitespace_removal_as_before_after(self):
        result = inline_spacing.check_document("値は ``foo``\t\nです\n")
        assert len(result.violations) == 1
        assert result.violations[0].text == ("literal の外部境界空白が不正（'``foo``\\t' → '``foo``'）")

    def test_does_not_report_rejected_or_unsupported(self):
        # x`a`y`b`z は equal-score/ambiguous interpreted-text chain — unsupported として no-touch
        result = inline_spacing.check_document("x`a`y`b`z 曖昧\n")
        assert result.violations == ()


class TestFixDocument:
    def test_no_accepted_candidates_returns_unchanged(self):
        source = "値は ``foo`` です\n"
        result = inline_spacing.fix_document(source)
        assert result.changed is False
        assert result.text == source
        assert result.transaction_failure is False

    def test_fixes_literal_boundary(self):
        result = inline_spacing.fix_document("値は``foo``です\n")
        assert result.changed is True
        assert result.text == "値は ``foo`` です\n"
        assert result.transaction_failure is False
        assert len(result.violations) == 1

    def test_mandatory_repair_succeeds_alongside_unprovable_candidate(self):
        # control.mixed.mandatory-plus-unprovable corpus ケース:
        # ``foo`` は mandatory repair、x`a`y`b`z は equal-score で unprovable。
        # unprovable は projection 前に除外され、mandatory repair の成功を妨げない。
        source = "値は``foo``ですと x`a`y`b`z 曖昧\n"
        expected = "値は ``foo`` ですと x`a`y`b`z 曖昧\n"
        result = inline_spacing.fix_document(source)
        assert result.changed is True
        assert result.text == expected

    def test_split_risk_does_not_block_independent_mandatory_repair(self):
        source = "値は``foo``です\n\n:ref:`a``b`\n"
        result = inline_spacing.fix_document(source)

        assert result.text == "値は ``foo`` です\n\n:ref:`a``b`\n"
        assert result.changed is True
        assert result.transaction_failure is False
        assert result.violations == (
            Violation(
                line=1,
                kind="literal",
                text="literal の外部境界空白が不正（'``foo``' → ' ``foo`` '）",
            ),
        )

    def test_adjacent_role_boundary_collapses_to_single_space(self):
        result = inline_spacing.fix_document(":ref:`a`:ref:`b` です\n")
        assert result.text == ":ref:`a` :ref:`b` です\n"

    def test_wide_boundary_before_existing_ascii_space_collapses_to_one_space(self):
        source = "値``a``\u3000 ``b``です\n"
        result = inline_spacing.fix_document(source)
        assert result.text == "値 ``a`` ``b`` です\n"
        assert result.changed is True
        assert result.transaction_failure is False

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            (
                "値``a``\u3000 ``b`` です\n",
                "値 ``a`` ``b`` です\n",
            ),
            (
                "値 ``a`` \u3000``b``です\n",
                "値 ``a`` ``b`` です\n",
            ),
            (
                "値``a``です、値``c``\u3000 ``d`` です\n",
                "値 ``a`` です、値 ``c`` ``d`` です\n",
            ),
        ],
    )
    def test_replacement_space_does_not_duplicate_untouched_gap(self, source, expected):
        result = inline_spacing.fix_document(source)
        assert result.text == expected
        assert result.changed is True
        assert result.transaction_failure is False

    def test_outer_strong_boundary_only_case_is_untouched(self):
        # interior は既に正しい境界を持ち、不足は outer ** の境界のみ（S4 #12 の責務）。
        # views.inline.decisions に accepted は無いため S3 は無変更のまま素通りする。
        source = "本文**a ``code`` b**です\n"
        result = inline_spacing.fix_document(source)
        assert result.changed is False
        assert result.text == source

    def test_idempotent_second_fix_is_noop(self):
        source = "値は``foo``です\n"
        first = inline_spacing.fix_document(source)
        second = inline_spacing.fix_document(first.text)
        assert second.changed is False
        assert second.text == first.text

    def test_same_family_partial_inline_edit_fails_closed(self):
        source = ":ref:`a``b`\n"
        result = inline_spacing.fix_document(source)
        assert result.text == source
        assert result.changed is False
        assert result.transaction_failure is True
        assert result.diagnostic is not None
        assert "split an existing inline" in result.diagnostic

    def test_same_family_guard_allows_different_kind_parent_reparse(self):
        result = inline_spacing.fix_document("**a``b``c**\n")
        assert result.text == "**a ``b`` c**\n"
        assert result.changed is True
        assert result.transaction_failure is False

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            (
                "設定は :ref:`config`直後に置き、:ref:`other` を参照\n",
                "設定は :ref:`config` 直後に置き、 :ref:`other` を参照\n",
            ),
            (
                "用語は :term:`SCIM`のとおり、:term:`X` を参照\n",
                "用語は :term:`SCIM` のとおり、 :term:`X` を参照\n",
            ),
            (
                ":ref:`a`:ref:`b`と:ref:`a`:ref:`b`\n",
                ":ref:`a` :ref:`b` と :ref:`a` :ref:`b`\n",
            ),
        ],
    )
    def test_repairs_glued_markup_misparsed_as_single_inline(self, source, expected):
        # docutils が境界不足の markup を 1 個の巨大 inline として誤 parse する入力でも、
        # candidate の切り出しが既存 inline の分割でなければ修正を拒否しない（PR #27 review claude H-3）。
        result = inline_spacing.fix_document(source)
        assert result.changed is True
        assert result.transaction_failure is False
        assert result.text == expected

    @pytest.mark.parametrize(
        "source",
        [
            "x　:ref:`a``b`\n",  # 全角空白を前置（gpt H-1）
            "x\t:ref:`a``b`\n",  # タブを前置（gpt H-1）
            ":ref:`a``b`です\n",  # grok H-1
            ":ref:`a``b`x\n",  # grok H-1
            "`a`_`b`_です\n",  # target_internal 版（grok H-1）
        ],
    )
    def test_split_of_existing_inline_fails_closed(self, source):
        # candidate の切り出しが既存 inline の分割 / parse 不能 run からの markup 新設に
        # あたる場合は無変更・transaction_failure（PR #27 review gpt H-1 / grok H-1）。
        result = inline_spacing.fix_document(source)
        assert result.text == source
        assert result.changed is False
        assert result.transaction_failure is True
        assert result.diagnostic is not None
        assert "split an existing inline" in result.diagnostic

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("``a``:ref:`b`です\n", "``a`` :ref:`b` です\n"),
            ("``x``:term:`y`と\n", "``x`` :term:`y` と\n"),
        ],
    )
    def test_split_guard_allows_role_after_recognized_literal(self, source, expected):
        result = inline_spacing.fix_document(source)
        assert result.text == expected
        assert result.changed is True
        assert result.transaction_failure is False

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            pytest.param(
                # 全角空白連結: 中間2トークンは unsupported のまま。末尾 accepted は
                # split-risk で除外され、先頭の独立した safe decision だけが適用される。
                ":ref:`a`:ref:`b`　:ref:`a`:ref:`b`\n",
                ":ref:`a` :ref:`b`　:ref:`a`:ref:`b`\n",
                id="ideographic-space-connector-partial",
            ),
            pytest.param(
                # null escape 連結: 同上（safe だけ適用、split-risk は除外）。
                ":ref:`a`:ref:`b`\\ :ref:`a`:ref:`b`\n",
                ":ref:`a` :ref:`b`\\ :ref:`a`:ref:`b`\n",
                id="null-escape-connector-partial",
            ),
            pytest.param(
                ":ref:`a`:ref:`b`と:ref:`a`:ref:`b`\n",
                ":ref:`a` :ref:`b` と :ref:`a` :ref:`b`\n",
                id="japanese-word-connector-repaired",
            ),
            pytest.param(
                ":ref:`a`:ref:`b` :ref:`a`:ref:`b`\n",
                ":ref:`a` :ref:`b` :ref:`a` :ref:`b`\n",
                id="half-width-space-connector-repaired",
            ),
        ],
    )
    def test_split_guard_outcome_is_connector_dependent(self, source, expected):
        """PR #27 final review F1 + Task 2: split guard の exemption は accepted
        candidate の markup にしか適用されず、S2 が unsupported
        (`overlapping-candidates`) に分類した well-formed な隣接トークンは exempt
        されない。そのため隣接する 4トークンを同じ連結子で結んでも、連結子の種類
        次第で結果が変わる。

        半角空白や「と」の連結子では両側が accepted に倒れるためガードは発火せず
        4トークンとも修正される。全角空白 / `\\ ` null escape の連結子では中間が
        unsupported のまま残り、末尾 accepted は split-risk として decision 単位で
        除外される一方、先頭の独立した safe decision は Task 2 により引き続き適用
        される（batch 全体の fail-closed にはしない）。

        これは受け入れ済みの既知の制限を固定するテストであり、望ましい仕様として
        pin しているわけではない。exemption を unsupported 側にも広げる変更を
        行う場合は、この対比が意図的に壊されたことを自覚した上で更新すること
        （S3 の follow-up: 別途 corpus 検証とレビューが必要）。
        """
        result = inline_spacing.fix_document(source)
        assert result.changed is True
        assert result.transaction_failure is False
        assert result.text == expected

    def test_forced_combined_proof_failure_no_write_diagnostic(self, monkeypatch):
        source = "値は``foo``です\n"
        real_parse = inline_spacing.parse_document
        parse_count = {"n": 0}

        def counting_parse(text):
            parse_count["n"] += 1
            return real_parse(text)

        real_build = inline_spacing.build_document_fingerprint

        def fake_build(text, *, edit_ranges=(), message_aliases=()):
            # projected fingerprint のみ build_document_fingerprint を通る。
            # 意図的に破損させ、untouched_inlines に無関係なノードを混入させて
            # proof を強制的に失敗させる。
            fp = real_build(text, edit_ranges=edit_ranges, message_aliases=message_aliases)
            return inline_spacing.DocumentFingerprint(
                untouched_inlines=fp.untouched_inlines + (("literal", "``corrupted``", "corrupted"),),
                blocks=fp.blocks,
                messages=fp.messages,
                truncated_from_line=fp.truncated_from_line,
            )

        monkeypatch.setattr(inline_spacing, "parse_document", counting_parse)
        monkeypatch.setattr(inline_spacing, "build_document_fingerprint", fake_build)
        result = inline_spacing.fix_document(source)
        assert result.transaction_failure is True
        assert result.changed is False
        assert result.text == source
        assert result.diagnostic is not None
        assert parse_count["n"] == 2  # S3 baseline + combined projection の2回のみ
        assert len(result.violations) == 1
        assert result.violations[0].line == 1
        assert "``foo``" in result.violations[0].text

    def test_overlapping_accepted_edits_is_transaction_failure(self, monkeypatch):
        # 防御的パス: S2 が重複した accepted を返した場合（本来発生しない）も
        # 書き込みせず transaction failure として扱う。
        source = "0123456789\n"
        decisions = (
            _decision(0, 5, "aaaaa"),
            _decision(3, 8, "bbbbb"),
        )
        fake_views = type(
            "FakeViews",
            (),
            {"inline": type("FakeInlineView", (), {"decisions": decisions})()},
        )()
        monkeypatch.setattr(inline_spacing, "classify_document", lambda _source: fake_views)
        result = inline_spacing.fix_document(source)
        assert result.transaction_failure is True
        assert result.changed is False
        assert result.text == source

    def test_fixes_literal_when_document_contains_named_embedded_uri(self):
        source = "詳細は `example <http://example.com>`_ を参照\n\n値は``foo``です\n"
        result = inline_spacing.fix_document(source)
        assert result.text == "詳細は `example <http://example.com>`_ を参照\n\n値は ``foo`` です\n"
        assert result.changed is True
        assert result.transaction_failure is False

    def test_fixes_literal_when_document_contains_substitution_image(self):
        source = ".. |img| image:: a.png\n\n図 |img| です\n\n値は``foo``です\n"
        result = inline_spacing.fix_document(source)
        assert result.text == ".. |img| image:: a.png\n\n図 |img| です\n\n値は ``foo`` です\n"
        assert result.changed is True
        assert result.transaction_failure is False

    def test_existing_title_warning_does_not_block_fix(self):
        source = "設定は``True``\n==========\n"
        result = inline_spacing.fix_document(source)
        assert result.text == "設定は ``True``\n==========\n"
        assert result.changed is True
        assert result.transaction_failure is False

    def test_new_title_warning_still_fails_closed(self):
        source = "設定は``True``\n==============\n"
        result = inline_spacing.fix_document(source)
        assert result.text == source
        assert result.changed is False
        assert result.transaction_failure is True
        assert "system message count increased" in result.diagnostic

    def test_title_warning_cannot_move_between_different_titles(self):
        source = "設定は``True``\n==============\n\n値は\\ ``False``\n==============\n"
        result = inline_spacing.fix_document(source)

        assert result.text == source
        assert result.changed is False
        assert result.transaction_failure is True
        assert result.diagnostic is not None
        assert "system message count increased" in result.diagnostic

    def test_ghost_rawsource_before_real_literal_fails_closed(self):
        # docutils は境界不足の先頭 ``a`` を literal と認識せず、後続の ``a`` だけが
        # oracle node になる。align_inlines_with_status は rawsource の先勝ち対応のため
        # その唯一の node を先頭（effect range 内のプレーンテキスト）へ張り付ける。
        # 位置確定後の除外により baseline の untouched が空になり、projected 側に残る
        # 後続 literal と不一致 → fail-closed（NUL mask 時代の誤成功を廃止した副作用）。
        # 正規の反復 literal の修正は test_fixes_between_repeated_identical_inlines が担保する。
        source = "値は``a``で ``a`` です\n"
        result = inline_spacing.fix_document(source)
        assert result.text == source
        assert result.changed is False
        assert result.transaction_failure is True
        assert result.diagnostic is not None
        assert "untouched inline markup changed" in result.diagnostic

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            (
                "設定は :ref:`config`直後に置く\n\n詳細は ``foo`` を参照\n",
                "設定は :ref:`config` 直後に置く\n\n詳細は ``foo`` を参照\n",
            ),
            (
                "用語は :term:`SCIM`のとおり\n\n``bar`` は必須です\n",
                "用語は :term:`SCIM` のとおり\n\n``bar`` は必須です\n",
            ),
        ],
    )
    def test_fixes_role_before_later_inline_without_masked_realign(self, source, expected):
        result = inline_spacing.fix_document(source)
        assert result.text == expected
        assert result.changed is True
        assert result.transaction_failure is False

    def test_fixes_between_repeated_identical_inlines(self):
        source = "既定は ``True`` です。\n\n値は``foo``です。\n\n設定は ``True`` を使う。\n"
        expected = source.replace("値は``foo``です。", "値は ``foo`` です。")
        result = inline_spacing.fix_document(source)
        assert result.text == expected
        assert result.changed is True
        assert result.transaction_failure is False

    def test_fixes_literal_with_multiple_substitution_images(self):
        source = ".. |a| image:: a.png\n.. |b| image:: b.png\n\n|a| と |b|\n\n値は``foo``です\n"
        expected = source.replace("値は``foo``です", "値は ``foo`` です")
        result = inline_spacing.fix_document(source)
        assert result.text == expected
        assert result.changed is True
        assert result.transaction_failure is False

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("**a**``b`` です\n", "**a** ``b`` です\n"),
            ("*a*``b`` です\n", "*a* ``b`` です\n"),
        ],
    )
    def test_fixes_literal_when_adjacent_markup_becomes_valid(self, source, expected):
        result = inline_spacing.fix_document(source)
        assert result.text == expected
        assert result.changed is True
        assert result.transaction_failure is False


# corpus の decision フィールドではなく、S2 の実際の accepted 有無を分岐条件にする。
#
# 元の理由だった 2 件の不整合（parity.role_spacing.test_adjacent_roles_no_false_positive,
# parity.inline_markup.test_allowed_punctuation_after_close が decision="unchanged" を
# 宣言しながら S2 は accepted を返す）は Issue #22 で解消済み。corpus 側が同一構文に
# 相互排他なルールを宣言していたのが原因で、視認性ルール採用の判断により両件とも
# repairable へ再宣言した。
#
# 分岐は別の理由で今も必要である。repairable 4 件（control.combined_proof.rejection,
# issue4.outer-strong-boundary.repairable, issue6.outer-strong-with-literal.missing-boundaries,
# issue6.outer-strong-with-role.missing-boundaries）は strong-spacing が所有するため
# inline view の accepted は空になる。所有者の違いを decision フィールドから判別できない
# ので、「S2 が accepted と判定したら S3 は必ず修正する」という契約だけを検証する。
class TestCorpusParametrization:
    @pytest.mark.parametrize("case", all_cases(), ids=lambda c: c.id)
    def test_matches_s2_classification_contract(self, case):
        views = classify_document(case.source)
        accepted = inline_spacing.accepted_decisions(views.inline.decisions)
        result = inline_spacing.fix_document(case.source)
        check_result = inline_spacing.check_document(case.source)

        if accepted:
            assert result.changed is True, case.id
            assert result.transaction_failure is False, case.id
            assert check_result.violations != (), case.id
            if case.expected is not None:
                assert result.text == case.expected, case.id
        else:
            assert result.changed is False, case.id
            assert result.text == case.source, case.id
            assert check_result.violations == (), case.id


class TestCheckerRunner:
    def test_no_rst_files_is_error(self, tmp_path):
        exit_code = _checker_runner.run_checker(
            [str(tmp_path)], fix=False, process=lambda text: _checker_runner.RunOutcome(violations=())
        )
        assert exit_code == 1

    def test_missing_path_is_warning_skip_not_fatal(self, tmp_path, capsys):
        rst = tmp_path / "a.rst"
        rst.write_text("valid\n", encoding="utf-8")
        missing = str(tmp_path / "does-not-exist.rst")
        exit_code = _checker_runner.run_checker(
            [str(rst), missing], fix=False, process=lambda text: _checker_runner.RunOutcome(violations=())
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "存在しない" in captured.err or "スキップ" in captured.err

    def test_non_rst_explicit_file_is_warning_skip(self, tmp_path):
        txt = tmp_path / "a.txt"
        txt.write_text("not rst\n", encoding="utf-8")
        exit_code = _checker_runner.run_checker(
            [str(txt)], fix=False, process=lambda text: _checker_runner.RunOutcome(violations=())
        )
        assert exit_code == 1  # 対象0件

    def test_io_error_on_unreadable_file(self, tmp_path):
        rst = tmp_path / "bad.rst"
        rst.write_bytes(b"\xff\xfe\x00\x01")  # 不正な utf-8
        exit_code = _checker_runner.run_checker(
            [str(rst)], fix=False, process=lambda text: _checker_runner.RunOutcome(violations=())
        )
        assert exit_code == 1

    def test_check_mode_violation_exits_1(self, tmp_path):
        rst = tmp_path / "a.rst"
        rst.write_text("値は``foo``です\n", encoding="utf-8")
        exit_code = _checker_runner.run_checker(
            [str(rst)],
            fix=False,
            process=lambda text: _checker_runner.RunOutcome(
                violations=(Violation(line=1, kind="literal", text="need space"),)
            ),
        )
        assert exit_code == 1
        assert rst.read_text(encoding="utf-8") == "値は``foo``です\n"  # check は書き込まない

    def test_check_mode_no_violation_exits_0(self, tmp_path):
        rst = tmp_path / "a.rst"
        rst.write_text("値は ``foo`` です\n", encoding="utf-8")
        exit_code = _checker_runner.run_checker(
            [str(rst)], fix=False, process=lambda text: _checker_runner.RunOutcome(violations=())
        )
        assert exit_code == 0

    def test_fix_mode_successful_fix_writes_and_exits_0(self, tmp_path):
        rst = tmp_path / "a.rst"
        rst.write_text("値は``foo``です\n", encoding="utf-8")
        exit_code = _checker_runner.run_checker(
            [str(rst)],
            fix=True,
            process=lambda text: _checker_runner.RunOutcome(
                violations=(Violation(line=1, kind="literal", text="fixed"),),
                fixed_text="値は ``foo`` です\n",
            ),
        )
        assert exit_code == 0
        assert rst.read_text(encoding="utf-8") == "値は ``foo`` です\n"

    def test_fix_mode_no_change_writes_nothing_exits_0(self, tmp_path):
        rst = tmp_path / "a.rst"
        rst.write_text("値は ``foo`` です\n", encoding="utf-8")
        exit_code = _checker_runner.run_checker(
            [str(rst)], fix=True, process=lambda text: _checker_runner.RunOutcome(violations=())
        )
        assert exit_code == 0

    def test_fix_mode_transaction_failure_no_write_exits_1(self, tmp_path, capsys):
        rst = tmp_path / "a.rst"
        original = "値は``foo``です\n"
        rst.write_text(original, encoding="utf-8")
        exit_code = _checker_runner.run_checker(
            [str(rst)],
            fix=True,
            process=lambda text: _checker_runner.RunOutcome(
                violations=(Violation(line=1, kind="literal", text="need space"),),
                transaction_failure=True,
                diagnostic="forced failure for test",
            ),
        )
        assert exit_code == 1
        assert rst.read_text(encoding="utf-8") == original  # 一切書き換えない
        captured = capsys.readouterr()
        assert f"{rst}:1: need space" in captured.err
        assert "forced failure for test" in captured.err

    def test_fix_mode_write_error_preserves_original_bytes_and_mode(self, tmp_path, capsys):
        """書き込み途中の OSError でも元ファイルの bytes/mode を完全保持する (H-1)。"""
        rst = tmp_path / "a.rst"
        original = b"short original content\n"
        rst.write_bytes(original)
        rst.chmod(0o640)
        original_mode = rst.stat().st_mode & 0o777
        long_fixed = "replacement content that is definitely longer than ten bytes\n"

        previous_handler = signal.getsignal(signal.SIGXFSZ)
        soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
        limited_hard = hard if hard == resource.RLIM_INFINITY or hard >= 10 else hard
        try:
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (10, limited_hard))
            exit_code = _checker_runner.run_checker(
                [str(rst)],
                fix=True,
                process=lambda text: _checker_runner.RunOutcome(
                    violations=(Violation(line=1, kind="literal", text="fixed"),),
                    fixed_text=long_fixed,
                ),
            )
        finally:
            resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))
            signal.signal(signal.SIGXFSZ, previous_handler)

        assert exit_code == 1
        assert rst.read_bytes() == original
        assert (rst.stat().st_mode & 0o777) == original_mode
        captured = capsys.readouterr()
        assert "書き込み失敗" in captured.err

    def test_fix_mode_preserves_permissions_on_success(self, tmp_path):
        rst = tmp_path / "a.rst"
        rst.write_text("値は``foo``です\n", encoding="utf-8")
        rst.chmod(0o640)
        exit_code = _checker_runner.run_checker(
            [str(rst)],
            fix=True,
            process=lambda text: _checker_runner.RunOutcome(
                violations=(Violation(line=1, kind="literal", text="fixed"),),
                fixed_text="値は ``foo`` です\n",
            ),
        )
        assert exit_code == 0
        assert rst.read_text(encoding="utf-8") == "値は ``foo`` です\n"
        assert (rst.stat().st_mode & 0o777) == 0o640

    @pytest.mark.parametrize("directory_input", [False, True], ids=["explicit", "directory"])
    def test_fix_mode_preserves_symlink_and_updates_target(self, tmp_path, directory_input):
        target = tmp_path / "source.rst"
        link = tmp_path / "alias.rst"
        target.write_text("値は``foo``です\n", encoding="utf-8")
        link.symlink_to(target)

        paths = [str(tmp_path)] if directory_input else [str(link)]
        exit_code = _checker_runner.run_checker(
            paths,
            fix=True,
            process=lambda text: _checker_runner.RunOutcome(
                violations=(Violation(line=1, kind="literal", text="fixed"),),
                fixed_text="値は ``foo`` です\n",
            ),
        )

        assert exit_code == 0
        assert link.is_symlink()
        assert link.resolve() == target.resolve()
        assert target.read_text(encoding="utf-8") == "値は ``foo`` です\n"
        assert link.read_text(encoding="utf-8") == "値は ``foo`` です\n"

    def test_dedup_and_first_occurrence_order(self, tmp_path):
        rst = tmp_path / "a.rst"
        rst.write_text("値は ``foo`` です\n", encoding="utf-8")
        seen: list[str] = []

        def process(text: str) -> _checker_runner.RunOutcome:
            seen.append(text)
            return _checker_runner.RunOutcome(violations=())

        exit_code = _checker_runner.run_checker([str(rst), str(rst)], fix=False, process=process)
        assert exit_code == 0
        assert len(seen) == 1  # ディレクトリ+同一ファイル指定の重複を dedupe 済み

    def test_normalizes_crlf_for_process_and_restores_it_on_write(self, tmp_path):
        rst = tmp_path / "crlf.rst"
        rst.write_bytes(b"before\r\nafter\r\n")
        seen: list[str] = []

        def process(text: str) -> _checker_runner.RunOutcome:
            seen.append(text)
            return _checker_runner.RunOutcome(
                violations=(Violation(line=1, kind="literal", text="fixed"),),
                fixed_text="fixed\nafter\n",
            )

        assert _checker_runner.run_checker([str(rst)], fix=True, process=process) == 0
        assert seen == ["before\nafter\n"]
        assert rst.read_bytes() == b"fixed\r\nafter\r\n"

    def test_rejects_single_string_path(self):
        with pytest.raises(TypeError, match="paths"):
            _checker_runner.run_checker(
                "a.rst",
                fix=True,
                process=lambda text: _checker_runner.RunOutcome(violations=()),
            )


class TestRun:
    def test_check_mode_end_to_end(self, tmp_path):
        rst = tmp_path / "a.rst"
        rst.write_text("値は``foo``です\n", encoding="utf-8")
        assert inline_spacing.run([str(rst)], fix=False) == 1
        assert rst.read_text(encoding="utf-8") == "値は``foo``です\n"

    def test_fix_mode_end_to_end_writes_fixed_text(self, tmp_path):
        rst = tmp_path / "a.rst"
        rst.write_text("値は``foo``です\n", encoding="utf-8")
        assert inline_spacing.run([str(rst)], fix=True) == 0
        assert rst.read_text(encoding="utf-8") == "値は ``foo`` です\n"

    def test_fix_mode_already_valid_exits_0_no_write(self, tmp_path):
        rst = tmp_path / "a.rst"
        original = "値は ``foo`` です\n"
        rst.write_text(original, encoding="utf-8")
        assert inline_spacing.run([str(rst)], fix=True) == 0
        assert rst.read_text(encoding="utf-8") == original

    def test_fix_mode_preserves_crlf_bytes(self, tmp_path):
        rst = tmp_path / "crlf.rst"
        rst.write_bytes("値は``foo``です\r\n変更しない行\r\n".encode("utf-8"))

        assert inline_spacing.run([str(rst)], fix=True) == 0
        assert rst.read_bytes() == "値は ``foo`` です\r\n変更しない行\r\n".encode("utf-8")

    @pytest.mark.parametrize(
        "source",
        [
            "終わりは ``完了。``\r\n",
            (
                "==============  ======\r\n"
                "col1            col2\r\n"
                "==============  ======\r\n"
                "値``a``x        ok\r\n"
                "==============  ======\r\n"
            ),
        ],
    )
    def test_crlf_does_not_change_inline_spacing_semantics(self, tmp_path, source):
        rst = tmp_path / "crlf.rst"
        original = source.encode("utf-8")
        rst.write_bytes(original)

        assert inline_spacing.run([str(rst)], fix=False) == 0
        assert inline_spacing.run([str(rst)], fix=True) == 0
        assert rst.read_bytes() == original

    def test_no_target_files_exits_1(self, tmp_path):
        assert inline_spacing.run([str(tmp_path)], fix=False) == 1
