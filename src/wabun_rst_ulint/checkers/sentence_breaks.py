"""docs/*.rst の「句点と改行」ルールを検出・修正する決定論的 lint。

RST 記述スタイルガイド「### 句点と改行」を機械的に検査・修正する。

- Rule1（文中改行）: 文中（全角括弧の外＝深度 0）の「。」直後で改行する。
  ``#.`` などのリスト項目では継続行をマーカー幅ぶん字下げする。括弧内の注記の「。」は維持する
- Rule2/3（末尾句点省略）: テキストブロック末尾（空行・セクション装飾・EOF の直前）の文末「。」を削除する

コード/リテラルブロック（``::`` 導入行やディレクティブ直後のインデント部）は対象外。
SentenceView の protected/unsupported 統合ケースは冪等。

使い方::

    uv run wabun-rst-ulint sentence-breaks --check docs/*.rst   # 違反の検出（違反ありで終了コード 1）
    uv run wabun-rst-ulint sentence-breaks --fix docs/*.rst     # ファイルを修正
"""

from __future__ import annotations

import bisect
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from wabun_rst_ulint.blocks import code_block_flags
from wabun_rst_ulint.checkers._inline_classifier import classify_document
from wabun_rst_ulint.fileset import collect_rst_files_pruned
from wabun_rst_ulint.reporting import Violation

_logger = logging.getLogger("wabun_rst_ulint.sentence_breaks")

# RST のセクション装飾（アンダーライン/オーバーライン）に使われる記号
_SECTION_CHARS = set("=-~\"'^`+*#:.")

# 括弧の対応（深度計算用）。深度 0 の「。」のみ文の区切りとみなす。全角・半角の両方を算入する
_OPEN_BRACKETS = set("（「『【［([")
_CLOSE_BRACKETS = set("）」』】］)]")
# 「。」の直後にあっても「後続の本文」とはみなさない閉じ記号
_TRAILING_CLOSERS = set("）」』】］)]")

# リスト項目のマーカー（``#.`` 自動採番・記号・数字）。継続行の字下げ幅算出に使う
_LIST_RE = re.compile(r"^(\s*)(#\.|#\)|[*+\-]|\d+\.|\d+\))(\s+)(.*)$")

# フィールドリスト（``:項目名: 本文``）の導入部。継続行の字下げ幅算出に使う
_FIELD_RE = re.compile(r"^(\s*:[^:]+:\s+)\S")

# ディレクティブ（``.. code-block:: python`` / ``.. mermaid::`` / ``.. list-table::`` 等）の導入行
_DIRECTIVE_RE = re.compile(r"^\s*\.\.\s+[\w-]+::")


def _indent_width(line: str) -> int:
    """行頭インデントの幅を返す（タブはタブ展開して数える）。"""
    body = line.lstrip(" \t")
    return len(line[: len(line) - len(body)].expandtabs())


def _is_directive_intro(line: str) -> bool:
    """``.. xxx::`` 形式のディレクティブ導入行か判定する。"""
    return bool(_DIRECTIVE_RE.match(line))


def _is_section_decoration(line: str) -> bool:
    """行がセクション装飾（``====`` など）のみで構成されるか判定する。"""
    s = line.strip()
    return len(s) >= 2 and all(c in _SECTION_CHARS for c in s)


def _is_block_end_after(next_line: str | None) -> bool:
    """直後の行がテキストブロックの終端（空行・セクション装飾・EOF）か判定する。"""
    if next_line is None:
        return True
    if next_line.strip() == "":
        return True
    return _is_section_decoration(next_line)


def _depth0_period_positions(line: str) -> list[int]:
    """括弧深度 0 にあり、後続に本文が続く（＝文の区切りである）「。」の位置を返す。"""
    depth = 0
    positions: list[int] = []
    for idx, ch in enumerate(line):
        if ch in _OPEN_BRACKETS:
            depth += 1
        elif ch in _CLOSE_BRACKETS:
            depth = max(0, depth - 1)
        elif ch == "。" and depth == 0:
            rest = line[idx + 1 :]
            if any(not c.isspace() and c not in _TRAILING_CLOSERS for c in rest):
                positions.append(idx)
    return positions


def _continuation_indent(line: str) -> int:
    """行を分割した際の継続行の字下げ幅を返す。

    リスト項目はマーカー幅、フィールドリストは本文開始列、それ以外は行頭インデントに合わせる。
    """
    m = _LIST_RE.match(line)
    if m:
        return len(m.group(1)) + len(m.group(2)) + len(m.group(3))
    mf = _FIELD_RE.match(line)
    if mf:
        return len(mf.group(1))
    return _indent_width(line)


@dataclass(frozen=True)
class _SourceLine:
    number: int
    start: int
    text: str
    in_code: bool
    unsupported: bool


@dataclass(frozen=True)
class _Analysis:
    source: str
    lines: tuple[_SourceLine, ...]
    line_starts: tuple[int, ...]
    protected: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: str


@dataclass(frozen=True)
class _ProjectedLine:
    text: str
    source_offsets: tuple[int | None, ...]


def _analyze(text: str) -> _Analysis:
    views = classify_document(text)
    raw_lines = text.split("\n")
    code = code_block_flags(raw_lines)
    unsupported = views.sentence.unsupported_lines
    lines: list[_SourceLine] = []
    starts: list[int] = []
    offset = 0
    for index, raw in enumerate(raw_lines):
        number = index + 1
        starts.append(offset)
        lines.append(_SourceLine(number, offset, raw, code[index], number in unsupported))
        offset += len(raw) + 1
    return _Analysis(
        source=text,
        lines=tuple(lines),
        line_starts=tuple(starts),
        protected=tuple(sorted((item.start, item.end) for item in views.sentence.protected)),
    )


def _is_protected(analysis: _Analysis, offset: int) -> bool:
    return any(start <= offset < end for start, end in analysis.protected)


def _source_line_at(analysis: _Analysis, offset: int) -> _SourceLine:
    index = bisect.bisect_right(analysis.line_starts, offset) - 1
    return analysis.lines[max(index, 0)]


def _rule1_positions(analysis: _Analysis, line: _SourceLine) -> tuple[int, ...]:
    if line.in_code or line.unsupported or _is_directive_intro(line.text):
        return ()
    return tuple(
        position
        for position in _depth0_period_positions(line.text)
        if not _is_protected(analysis, line.start + position)
    )


def _rule23_source_offset(analysis: _Analysis, line: _SourceLine) -> int | None:
    if line.in_code or line.unsupported:
        return None
    stripped = line.text.rstrip()
    if not stripped.endswith("。"):
        return None
    offset = line.start + len(stripped) - 1
    return None if _is_protected(analysis, offset) else offset


def _plan_rule1(analysis: _Analysis) -> list[_Edit]:
    edits: list[_Edit] = []
    for line in analysis.lines:
        indent = " " * _continuation_indent(line.text)
        for position in _rule1_positions(analysis, line):
            start = line.start + position + 1
            end = start
            while end < line.start + len(line.text) and analysis.source[end] == " ":
                end += 1
            edits.append(_Edit(start, end, "\n" + indent))
    return edits


def _project_lines(source: str, edits: list[_Edit]) -> list[_ProjectedLine]:
    projected: list[tuple[str, int | None]] = [(char, offset) for offset, char in enumerate(source)]
    for edit in sorted(edits, key=lambda item: item.start, reverse=True):
        replacement = [(char, None) for char in edit.replacement]
        projected[edit.start : edit.end] = replacement

    lines: list[_ProjectedLine] = []
    text_chars: list[str] = []
    offsets: list[int | None] = []
    for char, offset in projected:
        if char == "\n":
            lines.append(_ProjectedLine("".join(text_chars), tuple(offsets)))
            text_chars = []
            offsets = []
        else:
            text_chars.append(char)
            offsets.append(offset)
    lines.append(_ProjectedLine("".join(text_chars), tuple(offsets)))
    return lines


def _projected_period_offset(line: _ProjectedLine) -> int | None:
    stripped = line.text.rstrip()
    if not stripped.endswith("。"):
        return None
    return line.source_offsets[len(stripped) - 1]


def _plan_rule23(analysis: _Analysis, lines: list[_ProjectedLine]) -> list[_Edit]:
    edits: list[_Edit] = []
    for index, line in enumerate(lines):
        offset = _projected_period_offset(line)
        if offset is None:
            continue
        source_line = _source_line_at(analysis, offset)
        if source_line.in_code or source_line.unsupported or _is_protected(analysis, offset):
            continue
        next_text = lines[index + 1].text if index + 1 < len(lines) else None
        if _is_block_end_after(next_text):
            edits.append(_Edit(offset, offset + 1, ""))
    return edits


def _apply_edits(source: str, edits: list[_Edit]) -> str:
    result = source
    ordered = sorted(edits, key=lambda item: (item.start, item.end - item.start), reverse=True)
    for edit in ordered:
        result = result[: edit.start] + edit.replacement + result[edit.end :]
    return result


def find_violations(text: str) -> list[Violation]:
    """SentenceView を尊重して違反を元 physical line 上で列挙する。"""
    analysis = _analyze(text)
    violations: list[Violation] = []
    for index, line in enumerate(analysis.lines):
        if _rule1_positions(analysis, line):
            violations.append(Violation(line=line.number, kind="Rule1", text=line.text))

        offset = _rule23_source_offset(analysis, line)
        next_text = analysis.lines[index + 1].text if index + 1 < len(analysis.lines) else None
        if offset is not None and _is_block_end_after(next_text):
            violations.append(Violation(line=line.number, kind="Rule2/3", text=line.text))
    return violations


def fix_text(text: str) -> str:
    """SentenceView を尊重して「句点と改行」ルールを修正する。"""
    analysis = _analyze(text)
    rule1 = _plan_rule1(analysis)
    projected = _project_lines(text, rule1)
    rule23 = _plan_rule23(analysis, projected)
    return _apply_edits(text, [*rule1, *rule23])


def run(paths: list[Path], *, fix: bool, follow_symlinks: bool = False) -> int:
    """メイン処理。--check で検出（違反あり exit 1）、--fix で修正。

    読込・書込失敗は exit 2 で継続する。存在しないパスや非 .rst ファイルは
    警告付きでスキップし、.rst が 1 つも見つからなければ exit 1。
    ディレクトリは配下の .rst を再帰検索する（.venv 等の管理外ディレクトリは除外）。
    """
    files = collect_rst_files_pruned(paths, follow_symlinks=follow_symlinks, logger=_logger)
    if not files:
        print("エラー: .rst ファイルが見つかりませんでした", file=sys.stderr)
        return 1

    exit_code = 0
    total = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"読み込み失敗: {path}: {exc}", file=sys.stderr)
            exit_code = 2
            continue

        if fix:
            try:
                fixed = fix_text(text)
            except Exception as exc:
                print(f"分類失敗: {path}: {exc}", file=sys.stderr)
                exit_code = 2
                continue
            if fixed != text:
                try:
                    path.write_text(fixed, encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    print(f"書き込み失敗: {path}: {exc}", file=sys.stderr)
                    exit_code = 2
                    continue
                print(f"修正: {path}")
        else:
            try:
                violations = find_violations(text)
            except Exception as exc:
                print(f"分類失敗: {path}: {exc}", file=sys.stderr)
                exit_code = 2
                continue
            total += len(violations)
            for violation in violations:
                print(f"{path}:{violation.line}: [{violation.kind}] {violation.text.strip()}")

    if not fix and total > 0 and exit_code == 0:
        exit_code = 1
    return exit_code
