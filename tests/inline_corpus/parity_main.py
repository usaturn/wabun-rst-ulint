"""Parity corpus: every test from the four legacy checker modules."""

from __future__ import annotations

from tests.inline_corpus.cases import InlineCorpusCase

_BLOB = "https://github.com/usaturn/urst-checker/blob/d519812"


def _origin(test_path: str) -> str:
    return f"{_BLOB}/{test_path}"


def cases() -> list[InlineCorpusCase]:
    out: list[InlineCorpusCase] = []
    out.extend(_literal_spacing())
    out.extend(_role_spacing())
    out.extend(_role_visible_spacing())
    out.extend(_inline_markup())
    return out


def _literal_spacing() -> list[InlineCorpusCase]:
    p = "tests/test_literal_spacing.py"
    o = _origin(p)
    return [
        InlineCorpusCase(
            id="parity.literal_spacing.test_detects_missing_space_before_and_after",
            source="値は``foo``です\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo`` です\n",
            origin=o,
            notes="test_detects_missing_space_before_and_after",
        ),
        InlineCorpusCase(
            id="parity.literal_spacing.test_allowed_chars_no_violation",
            source="( ``foo`` )です。 ``bar``.\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=o,
            notes="test_allowed_chars_no_violation",
        ),
        InlineCorpusCase(
            id="parity.literal_spacing.test_allowed_chars_no_violation.comma",
            source="値は ``foo``, ``bar`` です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=o,
            notes="test_allowed_chars_no_violation (comma variant)",
        ),
        InlineCorpusCase(
            id="parity.literal_spacing.test_code_block_body_skipped",
            source=".. code-block:: text\n\n   x``y``z\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=o,
            notes="test_code_block_body_skipped",
        ),
        InlineCorpusCase(
            id="parity.literal_spacing.test_literal_block_trigger_line_checked_body_skipped",
            source="例は``foo``のとおり::\n\n   本文``内``は無視\n",
            decision="repairable",
            must_fix=True,
            expected="例は ``foo`` のとおり::\n\n   本文``内``は無視\n",
            origin=o,
            notes="test_literal_block_trigger_line_checked_body_skipped",
        ),
        InlineCorpusCase(
            id="parity.literal_spacing.test_fix_inserts_spaces",
            source="値は``foo``です\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo`` です\n",
            origin=o,
            notes="test_fix_inserts_spaces",
        ),
        InlineCorpusCase(
            id="parity.literal_spacing.test_fix_idempotent",
            source="値は``foo``です\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo`` です\n",
            origin=o,
            notes="test_fix_idempotent (second pass no-op is S3; declared output fixed)",
        ),
        InlineCorpusCase(
            id="parity.literal_spacing.test_run_exit_codes",
            source="値は``foo``です\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo`` です\n",
            origin=o,
            notes="test_run_exit_codes — content contract; exit mapping in schema tests",
        ),
        InlineCorpusCase(
            id="parity.literal_spacing.test_run_no_rst_files_is_error",
            source="",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=o,
            notes=(
                "test_run_no_rst_files_is_error — runner/IO contract deferred to S6; retained for parity completeness"
            ),
        ),
        InlineCorpusCase(
            id="parity.literal_spacing.test_fix_continues_after_write_error",
            source="値は``x``です\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``x`` です\n",
            origin=o,
            notes="test_fix_continues_after_write_error — content half; runner IO is S6",
        ),
    ]


def _role_spacing() -> list[InlineCorpusCase]:
    p = "tests/test_role_spacing.py"
    o = _origin(p)
    return [
        InlineCorpusCase(
            id="parity.role_spacing.test_detects_broken_start_after_fullwidth_close_paren",
            source="）:term:`SCIM` 同期\n",
            decision="repairable",
            must_fix=True,
            expected="） :term:`SCIM` 同期\n",
            origin=o,
            notes=(
                "test_detects_broken_start_after_fullwidth_close_paren; "
                "legacy inserted null-escape; redesign normal form is visible ASCII space"
            ),
        ),
        InlineCorpusCase(
            id="parity.role_spacing.test_detects_broken_end_before_kanji",
            source=":term:`SCIM`同期\n",
            decision="repairable",
            must_fix=True,
            expected=":term:`SCIM` 同期\n",
            origin=o,
            notes="test_detects_broken_end_before_kanji",
        ),
        InlineCorpusCase(
            id="parity.role_spacing.test_valid_boundaries_ok",
            source="これは :term:`SCIM` の説明\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=o,
            notes="test_valid_boundaries_ok",
        ),
        InlineCorpusCase(
            id="parity.role_spacing.test_valid_boundaries_ok.null-escape-form",
            source="（ :term:`Entra ID` では ）\\ :term:`SCIM` 同期\n",
            decision="repairable",
            must_fix=True,
            expected="（ :term:`Entra ID` では ） :term:`SCIM` 同期\n",
            origin=o,
            notes=(
                "test_valid_boundaries_ok second fixture; legacy accepted null-escape; "
                "redesign normalizes to visible space (intentionally changed decision)"
            ),
        ),
        InlineCorpusCase(
            id="parity.role_spacing.test_role_inside_inline_literal_ignored",
            source="``:term:`X`あ`` の説明\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=o,
            notes="test_role_inside_inline_literal_ignored",
        ),
        InlineCorpusCase(
            id="parity.role_spacing.test_adjacent_roles_no_false_positive",
            source=":ref:`a`:ref:`b`\n",
            decision="repairable",
            must_fix=True,
            expected=":ref:`a` :ref:`b`\n",
            origin=o,
            notes=(
                "test_adjacent_roles_no_false_positive — legacy role_spacing left adjacent "
                "roles alone, but role_visible_spacing repaired the identical construct "
                "(see parity.role_visible_spacing.test_adjacent_roles_single_insert, "
                "must_fix). One classifier cannot honour both. Issue #22 resolved in favour "
                "of the visible-spacing rule, so this case is re-declared repairable and "
                "intentionally diverges from the legacy role_spacing behaviour."
            ),
        ),
        InlineCorpusCase(
            id="parity.role_spacing.test_fix_inserts_null_escape_and_idempotent",
            source="）:term:`SCIM` 同期\n",
            decision="repairable",
            must_fix=True,
            expected="） :term:`SCIM` 同期\n",
            origin=o,
            notes=(
                "test_fix_inserts_null_escape_and_idempotent — intentional redesign: "
                "visible ASCII space replaces null-escape normal form"
            ),
        ),
        InlineCorpusCase(
            id="parity.role_spacing.test_code_block_skipped",
            source=".. code-block:: text\n\n   ）:term:`X`あ\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=o,
            notes="test_code_block_skipped",
        ),
        InlineCorpusCase(
            id="parity.role_spacing.test_run_exit_codes",
            source="）:term:`SCIM` 同期\n",
            decision="repairable",
            must_fix=True,
            expected="） :term:`SCIM` 同期\n",
            origin=o,
            notes="test_run_exit_codes",
        ),
    ]


def _role_visible_spacing() -> list[InlineCorpusCase]:
    p = "tests/test_role_visible_spacing.py"
    o = _origin(p)
    return [
        InlineCorpusCase(
            id="parity.role_visible_spacing.test_detects_missing_visible_space",
            source="中黒・:term:`X`・区切り\n",
            decision="repairable",
            must_fix=True,
            expected="中黒・ :term:`X` ・区切り\n",
            origin=o,
            notes="test_detects_missing_visible_space",
        ),
        InlineCorpusCase(
            id="parity.role_visible_spacing.test_cjk_punctuation_also_requires_space",
            source="これは :term:`X`。\n",
            decision="repairable",
            must_fix=True,
            expected="これは :term:`X` 。\n",
            origin=o,
            notes=(
                "test_cjk_punctuation_also_requires_space — legacy role-visible required "
                "space before CJK punct; redesign catalog may treat allowed-after punct "
                "as valid for some forms; retained as repairable per removed-checker parity"
            ),
        ),
        InlineCorpusCase(
            id="parity.role_visible_spacing.test_backslash_preserves_existing_null_escape",
            source=":term:`X`\\ （補足）\n",
            decision="repairable",
            must_fix=True,
            expected=":term:`X` （補足）\n",
            origin=o,
            notes=(
                "test_backslash_preserves_existing_null_escape — redesign normalizes "
                "null-escape to visible space (intentional decision change)"
            ),
        ),
        InlineCorpusCase(
            id="parity.role_visible_spacing.test_adjacent_roles_single_insert",
            source=":ref:`a`:ref:`b` です\n",
            decision="repairable",
            must_fix=True,
            expected=":ref:`a` :ref:`b` です\n",
            origin=o,
            notes="test_adjacent_roles_single_insert",
        ),
        InlineCorpusCase(
            id="parity.role_visible_spacing.test_substitution_definition_body_not_skipped",
            source=".. |m| replace:: x\n次の:term:`X` です\n",
            decision="repairable",
            must_fix=True,
            expected=".. |m| replace:: x\n次の :term:`X` です\n",
            origin=o,
            notes="test_substitution_definition_body_not_skipped",
        ),
        InlineCorpusCase(
            id="parity.role_visible_spacing.test_fix_and_idempotent",
            source="中黒・:term:`X`・区切り\n",
            decision="repairable",
            must_fix=True,
            expected="中黒・ :term:`X` ・区切り\n",
            origin=o,
            notes="test_fix_and_idempotent",
        ),
        InlineCorpusCase(
            id="parity.role_visible_spacing.test_run_exit_codes",
            source="中黒・:term:`X`・区切り\n",
            decision="repairable",
            must_fix=True,
            expected="中黒・ :term:`X` ・区切り\n",
            origin=o,
            notes="test_run_exit_codes",
        ),
    ]


def _inline_markup() -> list[InlineCorpusCase]:
    p = "tests/test_inline_markup.py"
    o = _origin(p)
    return [
        InlineCorpusCase(
            id="parity.inline_markup.test_broken_close_before_kanji_fixed",
            source=":term:`用語`直後\n",
            decision="repairable",
            must_fix=True,
            expected=":term:`用語` 直後\n",
            origin=o,
            notes=("test_broken_close_before_kanji_fixed — legacy null-escape; redesign visible space normal form"),
        ),
        InlineCorpusCase(
            id="parity.inline_markup.test_reference_suffix_handled",
            source="`phrase`_直後\n",
            decision="repairable",
            must_fix=True,
            expected="`phrase`_ 直後\n",
            origin=o,
            notes="test_reference_suffix_handled (visible space, not null-escape)",
        ),
        InlineCorpusCase(
            id="parity.inline_markup.test_internal_target_opener_not_close",
            source="_`target` です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=o,
            notes="test_internal_target_opener_not_close",
        ),
        InlineCorpusCase(
            id="parity.inline_markup.test_allowed_punctuation_after_close",
            source=":term:`X`。続き\n",
            decision="repairable",
            must_fix=True,
            expected=":term:`X` 。続き\n",
            origin=o,
            notes=(
                "test_allowed_punctuation_after_close — legacy inline_markup allowed CJK "
                "punctuation directly after a close, but role_visible_spacing required a "
                "space for the identical construct (see "
                "parity.role_visible_spacing.test_cjk_punctuation_also_requires_space, "
                "must_fix). One classifier cannot honour both. Issue #22 resolved in favour "
                "of the visible-spacing rule, so this case is re-declared repairable and "
                "intentionally diverges from the legacy inline_markup behaviour."
            ),
        ),
        InlineCorpusCase(
            id="parity.inline_markup.test_mermaid_directive_body_skipped",
            source=".. mermaid::\n\n   A[`x`後]\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=o,
            notes="test_mermaid_directive_body_skipped",
        ),
        InlineCorpusCase(
            id="parity.inline_markup.test_fix_idempotent",
            source=":term:`用語`直後\n",
            decision="repairable",
            must_fix=True,
            expected=":term:`用語` 直後\n",
            origin=o,
            notes="test_fix_idempotent",
        ),
        InlineCorpusCase(
            id="parity.inline_markup.test_run_check_mode_reports_and_exits_1",
            source=":term:`用語`直後\n",
            decision="repairable",
            must_fix=True,
            expected=":term:`用語` 直後\n",
            origin=o,
            notes="test_run_check_mode_reports_and_exits_1",
        ),
        InlineCorpusCase(
            id="parity.inline_markup.test_run_fix_mode_writes_and_exits_0",
            source=":term:`用語`直後\n",
            decision="repairable",
            must_fix=True,
            expected=":term:`用語` 直後\n",
            origin=o,
            notes="test_run_fix_mode_writes_and_exits_0",
        ),
        InlineCorpusCase(
            id="parity.inline_markup.test_run_missing_path_is_fatal",
            source="",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=o,
            notes="test_run_missing_path_is_fatal — runner IO deferred to S6",
        ),
        InlineCorpusCase(
            id="parity.inline_markup.test_run_continues_after_read_error",
            source=":term:`用語`直後\n",
            decision="repairable",
            must_fix=True,
            expected=":term:`用語` 直後\n",
            origin=o,
            notes="test_run_continues_after_read_error — content contract retained",
        ),
        InlineCorpusCase(
            id="parity.inline_markup.test_fix_continues_after_write_error",
            source=":term:`関連`直後\n",
            decision="repairable",
            must_fix=True,
            expected=":term:`関連` 直後\n",
            origin=o,
            notes="test_fix_continues_after_write_error",
        ),
        InlineCorpusCase(
            id="parity.inline_markup.test_run_io_error_only_returns_1",
            source="正常な文\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=o,
            notes="test_run_io_error_only_returns_1 — runner IO deferred to S6",
        ),
    ]
