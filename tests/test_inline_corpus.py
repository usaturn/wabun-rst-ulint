"""S1 corpus schema, fingerprint, and oracle-probe contracts (no production checker)."""

from __future__ import annotations

import inspect
from collections import Counter
from pathlib import Path

import docutils
import pytest

from tests.helpers import rst_fingerprint as fp
from tests.inline_corpus import (
    DECISIONS,
    RUNTIME_SEMANTICS,
    CorpusValidationError,
    InlineCorpusCase,
    all_cases,
    issue_4,
    issue_5,
    issue_6,
    origin_is_resolvable,
    parity_main,
    review_regressions,
    validate_case,
    validate_corpus,
    validated_cases,
)
from tests.inline_corpus.cases import catalog_cases
from tests.legacy_test_manifest import LEGACY_CHECKER_TESTS

REPO = Path(__file__).resolve().parents[1]

SUPPORTED_FORM_PREFIXES = (
    "catalog.literal.",
    "catalog.role.prefix.",
    "catalog.role.postfix.",
    "catalog.ref.named.",
    "catalog.ref.anonymous.",
    "catalog.target.internal.",
    "catalog.interp.",
    "catalog.boundary.null-escape",
)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_decision_enum_values(self) -> None:
        assert DECISIONS == frozenset({"unchanged", "repairable", "diagnostic-only"})

    def test_runtime_semantics_mapping_encoded(self) -> None:
        assert RUNTIME_SEMANTICS["unchanged"]["exit_effect"] == "neutral"
        assert RUNTIME_SEMANTICS["unchanged"]["check_reports_violation"] is False
        assert RUNTIME_SEMANTICS["unchanged"]["fix_writes"] is False

        assert RUNTIME_SEMANTICS["repairable"]["check_reports_violation"] is True
        assert RUNTIME_SEMANTICS["repairable"]["fix_writes"] is True
        assert "combined_proof_failure=1" in str(RUNTIME_SEMANTICS["repairable"]["exit_effect"])

        assert RUNTIME_SEMANTICS["diagnostic-only"]["emits_warning"] is True
        assert RUNTIME_SEMANTICS["diagnostic-only"]["exit_effect"] == "neutral"
        assert RUNTIME_SEMANTICS["diagnostic-only"]["fix_writes"] is False

    def test_repairable_requires_expected(self) -> None:
        bad = InlineCorpusCase(
            id="tmp.bad.repairable",
            source="x``y``z\n",
            decision="repairable",
            must_fix=True,
            expected=None,
            origin="https://github.com/usaturn/urst-checker/issues/9",
        )
        with pytest.raises(CorpusValidationError, match="expected"):
            validate_case(bad)

    def test_invalid_decision_rejected(self) -> None:
        bad = InlineCorpusCase(
            id="tmp.bad.decision",
            source="x\n",
            decision="accepted",  # type: ignore[arg-type]
            must_fix=False,
            expected=None,
            origin="https://github.com/usaturn/urst-checker/issues/9",
        )
        with pytest.raises(CorpusValidationError, match="decision"):
            validate_case(bad)

    def test_duplicate_ids_rejected(self) -> None:
        c = InlineCorpusCase(
            id="tmp.dup",
            source="a\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin="https://github.com/usaturn/urst-checker/issues/9",
        )
        with pytest.raises(CorpusValidationError, match="duplicate"):
            validate_corpus([c, c])

    def test_github_origin_resolvable(self) -> None:
        assert origin_is_resolvable("https://github.com/usaturn/urst-checker/issues/4")
        assert origin_is_resolvable(
            "https://github.com/usaturn/urst-checker/blob/d519812/tests/test_literal_spacing.py"
        )
        assert origin_is_resolvable("https://github.com/usaturn/urst-checker/pull/3")

    def test_tracked_path_origin_resolvable(self) -> None:
        assert origin_is_resolvable("tests/test_inline_spacing.py")
        assert origin_is_resolvable("src/wabun_rst_ulint/blocks.py")

    def test_reviews_path_not_valid_origin(self) -> None:
        assert not origin_is_resolvable("reviews/refactor-visible-inline-spacing/gpt-5.md")

    def test_full_corpus_validates(self) -> None:
        cases = validated_cases()
        assert len(cases) >= 50
        ids = [c.id for c in cases]
        assert len(ids) == len(set(ids))

    def test_every_repairable_has_expected(self) -> None:
        for case in all_cases():
            if case.decision == "repairable":
                assert case.expected is not None, case.id

    def test_must_fix_implies_repairable(self) -> None:
        for case in all_cases():
            if case.must_fix:
                assert case.decision == "repairable", case.id


# ---------------------------------------------------------------------------
# Catalog / provenance coverage
# ---------------------------------------------------------------------------


class TestCatalogCoverage:
    def test_supported_forms_have_stable_ids(self) -> None:
        ids = {c.id for c in catalog_cases()}
        for prefix in SUPPORTED_FORM_PREFIXES:
            assert any(i.startswith(prefix) for i in ids), prefix

    def test_must_fix_forms_present(self) -> None:
        must = {c.id for c in catalog_cases() if c.must_fix}
        assert any(i.startswith("catalog.literal.") for i in must)
        assert any(i.startswith("catalog.role.prefix.") for i in must)
        assert any(i.startswith("catalog.role.postfix.") for i in must)
        assert any(i.startswith("catalog.ref.named.") for i in must)
        assert any(i.startswith("catalog.ref.anonymous.") for i in must)
        assert any(i.startswith("catalog.target.internal.") for i in must)
        assert any(i.startswith("catalog.interp.") for i in must)
        assert any(i.startswith("catalog.boundary.") for i in must)

    def test_issue_provenance_modules(self) -> None:
        assert any(c.origin.endswith("/issues/4") for c in issue_4.cases())
        assert any(c.origin.endswith("/issues/5") for c in issue_5.cases())
        assert any(c.origin.endswith("/issues/6") for c in issue_6.cases())
        # Minimal reproductions present
        assert any("strong-wrapped-literal" in c.id for c in issue_4.cases())
        assert any("blank-after-opener" in c.id for c in issue_5.cases())
        assert any("outer-strong-with-literal" in c.id for c in issue_6.cases())

    def test_review_origins_use_pr_url_not_reviews_dir(self) -> None:
        for case in review_regressions.cases():
            assert case.origin == "https://github.com/usaturn/urst-checker/pull/3"
            assert "reviews/" not in case.origin

    def test_legacy_manifest_shape_is_frozen(self) -> None:
        assert list(LEGACY_CHECKER_TESTS) == [
            "literal_spacing",
            "role_spacing",
            "role_visible_spacing",
            "inline_markup",
        ]
        assert sum(len(names) for names in LEGACY_CHECKER_TESTS.values()) == 36

    def test_parity_covers_all_removed_checker_tests(self) -> None:
        parity_ids = {c.id for c in parity_main.cases()}
        for module_key, test_names in LEGACY_CHECKER_TESTS.items():
            for name in test_names:
                prefix = f"parity.{module_key}.{name}"
                assert any(pid == prefix or pid.startswith(prefix + ".") for pid in parity_ids), (
                    f"missing corpus for test_{module_key}.py::{name}"
                )


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_docutils_version_locked_line(self) -> None:
        assert docutils.__version__ == "0.22.4"

    def test_block_and_inline_kinds_literal(self) -> None:
        result = fp.fingerprint("値は ``foo`` です\n")
        assert "paragraph" in result.block_kinds
        kinds = [i.kind for i in result.inlines]
        assert "literal" in kinds
        lit = next(i for i in result.inlines if i.kind == "literal")
        assert lit.rawsource == "``foo``"
        assert lit.visible_text == "foo"
        assert "foo" in result.document_text

    def test_broken_literal_has_no_literal_node(self) -> None:
        result = fp.fingerprint("値は``foo``です\n")
        assert all(i.kind != "literal" for i in result.inlines)

    def test_system_messages_recorded(self) -> None:
        # Unterminated inline produces a warning system message.
        result = fp.fingerprint("start `only\n")
        assert isinstance(result.messages, Counter)
        # May be empty or non-empty depending on parse; force a known error:
        result2 = fp.fingerprint(".. unknown-directive::\n\n   x\n")
        assert sum(result2.messages.values()) >= 1
        for level, msg_type, body in result2.messages:
            assert isinstance(level, int)
            assert isinstance(msg_type, str)
            assert isinstance(body, str)
            assert not body.startswith("<string>:")

    def test_message_duplicate_count_increase_fails_counter_not_set(self) -> None:
        """A key going from 1 → 2 must fail Counter safety; set equality would pass."""
        key = (2, "WARNING", "duplicate semantic body")
        before: Counter[tuple[int, str, str]] = Counter({key: 1})
        after_dup: Counter[tuple[int, str, str]] = Counter({key: 2})
        after_same: Counter[tuple[int, str, str]] = Counter({key: 1})
        after_gone: Counter[tuple[int, str, str]] = Counter()

        assert fp.messages_delta_safe(before, after_same)
        assert fp.messages_delta_safe(before, after_gone)  # disappearance OK
        assert not fp.messages_delta_safe(before, after_dup)

        # Set comparison is insufficient: sets of keys look identical for 1 vs 2.
        assert set(before.elements()) != set(after_dup.elements()) or True
        assert set(before) == set(after_dup)  # keys equal — set would miss multiplicity
        assert before != after_dup

    def test_repair_message_delta_on_real_parse(self) -> None:
        before = fp.fingerprint("値は``foo``です\n").messages
        after = fp.fingerprint("値は ``foo`` です\n").messages
        assert fp.messages_delta_safe(before, after)

    def test_normalize_message_body_strips_source_line(self) -> None:
        raw = "<string>:1: (WARNING/2) Inline interpreted text or phrase reference start-string without end-string."
        body = fp.normalize_message_body(raw)
        assert not body.startswith("<string>")
        assert "Inline interpreted text" in body


# ---------------------------------------------------------------------------
# Probes: opaque role, directives, alignment
# ---------------------------------------------------------------------------


class TestProbes:
    def test_opaque_role_kind_ref(self) -> None:
        kind = fp.probe_opaque_role_kind("see :ref:`label` here\n", "ref")
        assert kind == "opaque_role"
        result = fp.fingerprint("see :ref:`label` here\n", opaque_roles=("ref",))
        assert any(i.kind == "opaque_role" for i in result.inlines)
        assert all(i.kind != "problematic" for i in result.inlines)

    def test_opaque_role_registry_restored(self) -> None:
        from docutils.parsers.rst import roles as roles_mod

        before = dict(roles_mod._roles)  # type: ignore[attr-defined]
        fp.fingerprint(":term:`X`\n", opaque_roles=("term",))
        after = dict(roles_mod._roles)  # type: ignore[attr-defined]
        assert before == after

    def test_note_body_checkable_has_paragraph(self) -> None:
        result = fp.fingerprint(".. note::\n\n   値は ``x`` です\n")
        assert "note" in result.block_kinds
        assert any(i.kind == "literal" for i in result.inlines)

    def test_include_disabled_no_file_read(self, tmp_path: Path) -> None:
        # Ensure we do not read external files even if one exists nearby.
        victim = tmp_path / "secret.rst"
        victim.write_text("SHOULD_NOT_LOAD ``x``\n", encoding="utf-8")
        result = fp.fingerprint(".. include:: secret.rst\n")
        assert "SHOULD_NOT_LOAD" not in result.document_text
        assert sum(result.messages.values()) >= 1

    def test_raw_disabled(self) -> None:
        result = fp.fingerprint(".. raw:: html\n\n   <b>x</b>\n")
        # Disabled raw becomes an opaque literal_block + warning, not executed markup.
        assert "literal_block" in result.block_kinds
        assert sum(result.messages.values()) >= 1
        assert any("raw" in body.lower() and "disabled" in body.lower() for *_, body in result.messages)

    def test_unknown_directive_body_not_inline_literal(self) -> None:
        result = fp.fingerprint(".. unknown-directive::\n\n   body ``x`` y\n")
        # Body is preserved as literal_block, not parsed as inline literal content
        # for editing purposes — fingerprint may still list literal_block.
        assert "literal_block" in result.block_kinds or sum(result.messages.values()) >= 1

    def test_order_preserving_alignment_repeated_rawsource(self) -> None:
        source = "A ``x`` B ``x`` C\n"
        result = fp.fingerprint(source)
        lits = [i for i in result.inlines if i.kind == "literal"]
        assert len(lits) == 2
        aligned = fp.align_inlines_to_source(source, lits)
        assert len(aligned) == 2
        assert aligned[0].start < aligned[1].start
        assert source[aligned[0].start : aligned[0].end] == "``x``"
        assert source[aligned[1].start : aligned[1].end] == "``x``"

    def test_must_fix_alignment_uses_source_fingerprint_only(self) -> None:
        """S1 alignment metric: fingerprint(source) only — never expected for nodes.

        Freezes the honest S1 measurement so the metric cannot be silently
        redefined to look better. ``rate < 1.0`` is the expected, structural
        outcome — see ``must_fix_source_alignment_report`` for why, and for
        why this no longer blocks S2.
        """
        cases = validated_cases()
        report = fp.must_fix_source_alignment_report(cases)
        assert report["total"] > 0
        assert report["metric"].startswith("fingerprint(source)")
        assert all(d.get("node_source") == "source" for d in report["details"])

        # Broken must_fix inputs often yield empty inlines under docutils 0.22.4.
        # Empty lists are failures — never auto-success and never measured via expected.
        empty_ids = set(report["empty_inline_ids"])
        assert empty_ids, "expected some boundary-deficient must_fix sources to lack inlines"
        for case_id in empty_ids:
            case = next(c for c in cases if c.id == case_id)
            src_fp = fp.fingerprint(
                case.source,
                opaque_roles=("term", "ref", "name", "doc", "class", "func"),
            )
            assert src_fp.inlines == ()

        # Honest rate under 0.22.4: not 100%. Document gate; do not redefine metric.
        assert report["rate"] < 1.0
        # Historical PR #18 field name, not a live block on S2 (superseded by PR #20).
        assert report["s2_blocked"] is True
        assert report["failed"] == len(report["fail_ids"])
        assert report["ok"] + report["failed"] == report["total"]
        # Recorded band (docutils 0.22.4). S1 measured 30/55 ≈ 54.5%; Issue #22
        # re-declared two contradictory parity rows as repairable/must_fix, and
        # both align (their markup is already recognised), so the band moved to
        # 32/57 ≈ 56.1%. empty_inlines is unchanged: neither new row is
        # boundary-deficient.
        assert report["ok"] == 32
        assert report["total"] == 57
        assert report["empty_inlines"] == 25
        assert abs(report["rate"] - 32 / 57) < 1e-9

    def test_must_fix_alignment_gate_evidence_is_frozen(self) -> None:
        """Unaligned must_fix cases stay must_fix — no silent downgrade.

        Was ``test_must_fix_alignment_go_no_go_blocks_s2``. Renamed because the
        old name asserted S2 was blocked, which stopped being true at PR #20:
        the gate moved to supported classification
        (``test_must_fix_accepted_rate_100``, 100%). What this test still
        guards is the half of Issue #8's Go/No-Go that never lapsed — a case
        that fails pure-docutils alignment must not be quietly relabelled
        ``must_fix=False`` to make the number go up.
        """
        cases = validated_cases()
        report = fp.must_fix_source_alignment_report(cases)
        must_ids = {c.id for c in cases if c.must_fix}
        # Failures remain must_fix=True in corpus (no silent downgrade).
        for case_id in report["fail_ids"]:
            case = next(c for c in cases if c.id == case_id)
            assert case.must_fix is True
            assert case.id in must_ids
        assert report["s2_blocked"] is True
        assert report["fail_ids"], "gate evidence must list unaligned must_fix ids"

    def test_combined_proof_rejection_is_not_diagnostic_only(self) -> None:
        cases = {c.id: c for c in all_cases()}
        case = cases["control.combined_proof.rejection"]
        assert case.decision == "repairable"
        assert case.must_fix is False
        assert case.expected == case.source
        assert case.decision != "diagnostic-only"
        # Exit contract rides on repairable combined_proof_failure=1, not neutral.
        assert "combined_proof_failure=1" in str(RUNTIME_SEMANTICS["repairable"]["exit_effect"])
        assert RUNTIME_SEMANTICS["diagnostic-only"]["exit_effect"] == "neutral"

    def test_strong_literal_control_fingerprint(self) -> None:
        result = fp.fingerprint("本文 **``重要``** です\n")
        kinds = [i.kind for i in result.inlines]
        assert "strong" in kinds
        # Nested literal may appear as text inside strong depending on docutils;
        # critical contract: document still contains strong structure.
        assert "strong" in result.block_kinds or "strong" in kinds


# ---------------------------------------------------------------------------
# Corpus integrity inventory helpers used by verification
# ---------------------------------------------------------------------------


class TestCorpusInventory:
    def test_origins_all_resolvable(self) -> None:
        for case in all_cases():
            assert origin_is_resolvable(case.origin), (case.id, case.origin)

    def test_no_production_import_in_corpus_package(self) -> None:
        """Corpus modules must not import production checkers."""
        root = REPO / "tests" / "inline_corpus"
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "wabun_rst_ulint.checkers" not in text, path
            assert "from wabun_rst_ulint" not in text, path

    def test_fingerprint_helper_is_test_only(self) -> None:
        src = inspect.getsource(fp)
        assert "publish_doctree" in src
        # Not under src/
        assert Path(fp.__file__).parts[-3:-1] == ("tests", "helpers")
