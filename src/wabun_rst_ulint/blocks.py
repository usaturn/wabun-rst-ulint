"""コード/リテラルブロック・コメントのスキップ判定。

2 方式が存在し、元スクリプトの意図的な差異のため統一しない:

- build_skip_mask: heading-width 用（expecting_block マスク方式・indent >= 基準）
- code_block_flags: sentence-breaks 用（導入行の次行以降のみフラグ）
"""

from __future__ import annotations

import re

# RST ディレクティブ行を検出する正規表現: .. name::
DEFAULT_DIRECTIVE_RE = re.compile(r"^\.\.\s+(\S+)::")

# 本文がコード/リテラルであり検査対象外とするディレクティブ
SKIP_BODY_DIRECTIVES = frozenset(
    {
        "code-block",
        "code",
        "sourcecode",
        "literalinclude",
        "raw",
        "parsed-literal",
        "math",
        "highlight",
    }
)


def build_skip_mask(raw_lines: list[str]) -> list[bool]:
    """各行がコードブロック / リテラルブロック / コメント本文として
    adornment 検出をスキップすべきかを示すブール配列を返す。

    True の行は adornment 検出対象外。
    """
    mask = [False] * len(raw_lines)
    in_block = False
    expecting_block = False
    block_indent: int | None = None

    for line_idx, raw_line in enumerate(raw_lines):
        stripped = raw_line.rstrip()

        if expecting_block:
            if stripped == "":
                mask[line_idx] = True
                continue
            if stripped[0] in (" ", "\t"):
                in_block = True
                expecting_block = False
                block_indent = len(stripped) - len(stripped.lstrip())
                mask[line_idx] = True
                continue
            else:
                expecting_block = False
                # この行はブロック対象外として通常処理に移行

        if in_block:
            if stripped == "":
                mask[line_idx] = True
                continue
            indent = len(stripped) - len(stripped.lstrip())
            if block_indent is not None and indent >= block_indent:
                mask[line_idx] = True
                continue
            else:
                in_block = False
                block_indent = None

        lstripped = stripped.lstrip()
        is_directive_line = False
        if lstripped.startswith(".. ") or lstripped == "..":
            directive_match = DEFAULT_DIRECTIVE_RE.match(lstripped)
            if directive_match:
                directive_name = directive_match.group(1).lower()
                if directive_name in SKIP_BODY_DIRECTIVES:
                    expecting_block = True
                    # ディレクティブ行自体は adornment にはなり得ないため True とする
                    mask[line_idx] = True
                    continue
                # 通常ディレクティブ行（note, warning 等）はマスク不要
                # ただし末尾が :: で終わるためリテラルブロックトリガーとは
                # 区別する必要がある
                is_directive_line = True
            else:
                # コメント行 → 本文をスキップ
                expecting_block = True
                mask[line_idx] = True
                continue

        # 行末 :: のリテラルブロックトリガー
        # ディレクティブ宣言行（.. note:: 等）は :: で終わるが
        # リテラルブロック開始ではないため除外する
        if not is_directive_line and stripped.endswith("::"):
            expecting_block = True
            # この行自体は通常テキストとして扱う

    return mask


# ディレクティブ（``.. code-block:: python`` 等）の導入行（sentence-breaks 専用）
_SENTENCE_DIRECTIVE_RE = re.compile(r"^\s*\.\.\s+[\w-]+::")


def _sentence_indent_width(line: str) -> int:
    """行頭インデントの幅を返す（タブはタブ展開して数える）。"""
    body = line.lstrip(" \t")
    return len(line[: len(line) - len(body)].expandtabs())


def code_block_flags(lines: list[str]) -> list[bool]:
    """コード/リテラルブロック（``::`` 導入行やディレクティブ直後のインデント部）を True にする。"""
    flags = [False] * len(lines)
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        is_intro = line.rstrip().endswith("::") or bool(_SENTENCE_DIRECTIVE_RE.match(line))
        if is_intro:
            intro_indent = _sentence_indent_width(line)
            j = i + 1
            while j < n:
                inner = lines[j]
                if inner.strip() == "":
                    j += 1
                    continue
                if _sentence_indent_width(inner) > intro_indent:
                    flags[j] = True
                    j += 1
                else:
                    break
            i = j
            continue
        i += 1
    return flags
