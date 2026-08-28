"""Issue #14 で削除したレガシーチェッカーテストの不変マニフェスト。

これは履歴上のテスト証拠であり、production の互換コードではない。
削除された 4 ファイルのトップレベル `test_` 関数名を凍結し、
S1 パリティコーパス（`tests/inline_corpus/parity_main.py`）が
それら全件を `parity.<module>.<test>` の id で覆っていることを
ファイルシステム走査なしに検証できるようにする。

このデータは追記も削除もしない。削除済みファイルの過去の内容そのものである。
"""

from __future__ import annotations

LEGACY_CHECKER_TESTS: dict[str, tuple[str, ...]] = {
    "literal_spacing": (
        "test_detects_missing_space_before_and_after",
        "test_allowed_chars_no_violation",
        "test_code_block_body_skipped",
        "test_literal_block_trigger_line_checked_body_skipped",
        "test_fix_inserts_spaces",
        "test_fix_idempotent",
        "test_run_exit_codes",
        "test_run_no_rst_files_is_error",
        "test_fix_continues_after_write_error",
    ),
    "role_spacing": (
        "test_detects_broken_start_after_fullwidth_close_paren",
        "test_detects_broken_end_before_kanji",
        "test_valid_boundaries_ok",
        "test_role_inside_inline_literal_ignored",
        "test_adjacent_roles_no_false_positive",
        "test_fix_inserts_null_escape_and_idempotent",
        "test_code_block_skipped",
        "test_run_exit_codes",
    ),
    "role_visible_spacing": (
        "test_detects_missing_visible_space",
        "test_cjk_punctuation_also_requires_space",
        "test_backslash_preserves_existing_null_escape",
        "test_adjacent_roles_single_insert",
        "test_substitution_definition_body_not_skipped",
        "test_fix_and_idempotent",
        "test_run_exit_codes",
    ),
    "inline_markup": (
        "test_broken_close_before_kanji_fixed",
        "test_reference_suffix_handled",
        "test_internal_target_opener_not_close",
        "test_allowed_punctuation_after_close",
        "test_mermaid_directive_body_skipped",
        "test_fix_idempotent",
        "test_run_check_mode_reports_and_exits_1",
        "test_run_fix_mode_writes_and_exits_0",
        "test_run_missing_path_is_fatal",
        "test_run_continues_after_read_error",
        "test_fix_continues_after_write_error",
        "test_run_io_error_only_returns_1",
    ),
}
