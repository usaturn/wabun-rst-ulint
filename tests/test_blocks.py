"""blocks モジュールのテスト。"""

from wabun_rst_ulint.blocks import build_skip_mask, code_block_flags


def test_build_skip_mask_marks_code_body():
    lines = [
        "タイトル\n",
        "========\n",
        "\n",
        ".. code-block:: text\n",
        "\n",
        "   ====\n",
        "\n",
        "本文\n",
    ]
    mask = build_skip_mask(lines)
    assert mask == [False, False, False, True, True, True, True, False]


def test_code_block_flags_sentence_breaks():
    lines = ["例::", "", "   コード。", "本文。"]
    assert code_block_flags(lines) == [False, False, True, False]


def test_legacy_only_helpers_removed():
    """Issue #14: レガシーチェッカー専用ヘルパーは残さない。"""
    import wabun_rst_ulint.blocks as blocks

    assert not hasattr(blocks, "iter_checkable_lines")
    assert not hasattr(blocks, "indent_width_tabs8")
    assert not hasattr(blocks, "SUBSTITUTION_DIRECTIVE_RE")
