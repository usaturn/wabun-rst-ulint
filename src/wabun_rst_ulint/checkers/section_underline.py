"""RST セクションタイトル下線・上下線の表示幅チェック・修正スクリプト（CLI 公開名: heading-width）

reStructuredText のセクションタイトル下線（および上下線ペア）が、
タイトルのマルチバイト表示幅と一致しない場合に検出し、 ``--fix`` で
自動修正することで Sphinx の ``Title underline too short.`` WARNING を解消する。

東アジア全角文字（CJK 漢字・ひらがな・カタカナ等）は表示幅 2 として扱い、
タイトル文字列の合計表示幅と adornment 行の文字数が一致するかを検査する。

動作仕様:
    - ``--fix`` 時、adornment 行は ``char * width`` で再生成されるため、元行に末尾空白がある場合は除去される
    - ``--fix`` の書き込みは tempfile + os.replace により原子的（中断時のファイル破損を回避）
    - シンボリックリンクは ``--follow-symlinks`` 指定時のみ検査対象に含める
    - ``.git``、``.venv``、``__pycache__``、``node_modules`` 等の管理外ディレクトリは ``rglob`` の結果から除外する

使用例:
    uv run wabun-rst-ulint heading-width docs/
    uv run wabun-rst-ulint heading-width \\
        docs/operational_documentation/query_alb_logs/query_alb_logs_operations_manual.rst
    uv run wabun-rst-ulint heading-width --fix docs/
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path

from wabun_rst_ulint.blocks import build_skip_mask
from wabun_rst_ulint.fileset import collect_rst_files_pruned
from wabun_rst_ulint.reporting import SEPARATOR, Violation, log_header, setup_logging

logger = logging.getLogger(__name__)

# adornment として使用可能な文字（docutils 仕様準拠）
ADORNMENT_CHARS = "=-`:.'\"~^_*+#<>"

# adornment 行を判定する正規表現（同一文字を 3 文字以上連続）
ADORNMENT_RE = re.compile(r"^([" + re.escape(ADORNMENT_CHARS) + r"])\1{2,}\s*$")


def _display_width(text: str) -> int:
    """文字列の表示幅を計算する。

    east_asian_width が F / W のとき 2、それ以外（A / H / N / Na）は 1 として扱う。
    """
    width = 0
    for char in text:
        eaw = unicodedata.east_asian_width(char)
        if eaw in ("F", "W"):
            width += 2
        else:
            width += 1
    return width


def _is_adornment_line(stripped: str) -> bool:
    """adornment 行かどうか判定する。

    末尾の空白を除いた状態で、同一の adornment 文字が 3 文字以上連続している場合に True。
    """
    return bool(ADORNMENT_RE.match(stripped))


def _adornment_char(stripped: str) -> str:
    """adornment 行の文字を返す。adornment 行でない場合の挙動は未定義。"""
    return stripped[0]


def _adornment_length(stripped: str) -> int:
    """adornment 行の文字数（末尾空白を除く）を返す。"""
    return len(stripped.rstrip())


def _detect_violations(
    raw_lines: list[str],
    skip_mask: list[bool],
) -> tuple[list[Violation], dict[int, tuple[str, int]]]:
    """違反を検出し、修正計画を返す。

    Returns:
        (violations, fix_plan)
        violations: 検出した Violation のリスト
        fix_plan: line_idx -> (新しい adornment 文字, 表示幅) の辞書
    """
    violations: list[Violation] = []
    fix_plan: dict[int, tuple[str, int]] = {}

    n = len(raw_lines)
    i = 0
    while i < n:
        if skip_mask[i]:
            i += 1
            continue

        stripped = raw_lines[i].rstrip()

        if not _is_adornment_line(stripped):
            i += 1
            continue

        # i 行目が adornment 行
        # パターン B（オーバーライン + アンダーライン）の判定を優先する
        # i: adornment, i+1: タイトル, i+2: adornment（同一文字・同一長）
        is_pattern_b = False
        if i + 2 < n and not skip_mask[i + 1] and not skip_mask[i + 2]:
            title_line = raw_lines[i + 1].rstrip()
            below = raw_lines[i + 2].rstrip()
            if title_line != "" and not _is_adornment_line(title_line) and _is_adornment_line(below):
                is_pattern_b = True

        if is_pattern_b:
            over = stripped
            title_line = raw_lines[i + 1].rstrip()
            under = raw_lines[i + 2].rstrip()
            title_text = title_line.strip()
            width = _display_width(title_text)
            over_char = _adornment_char(over)
            under_char = _adornment_char(under)
            over_len = _adornment_length(over)
            under_len = _adornment_length(under)
            line_num = i + 1  # 上線の行番号（1-based）

            mismatch = False
            details: list[str] = []
            if over_char != under_char:
                mismatch = True
                details.append(f"上下線文字不一致 over='{over_char}' under='{under_char}'")
            if over_len != under_len:
                mismatch = True
                details.append(f"上下線長不一致 over_len={over_len} under_len={under_len}")
            if over_len != width or under_len != width:
                mismatch = True
                details.append(f"title=({title_text})(width={width}) over_len={over_len} under_len={under_len}")

            if mismatch:
                # 修正用の adornment 文字を決定する（上下線一致なら共通文字、不一致なら下線文字を優先）
                fix_char = under_char if over_char != under_char else over_char
                violations.append(
                    Violation(
                        line=line_num,
                        kind="セクション上下線",
                        text=(
                            f"title=({title_text})(width={width}) over='{over_char}'(len={over_len}) "
                            f"under='{under_char}'(len={under_len}) -> '{fix_char}'*{width}"
                        ),
                    )
                )
                fix_plan[i] = (fix_char, width)
                fix_plan[i + 2] = (fix_char, width)

            # i, i+1, i+2 を消費
            i += 3
            continue

        # パターン A（アンダーラインのみ）の判定
        # 直前行（i-1）がタイトル候補、直前々行（i-2）が空行 / ファイル先頭 / 別 adornment
        if i >= 1 and not skip_mask[i - 1]:
            title_line = raw_lines[i - 1].rstrip()
            if title_line != "" and not _is_adornment_line(title_line):
                # 直前々行の確認（i-2）
                ok_prev = False
                if i - 2 < 0:
                    ok_prev = True
                else:
                    prev2 = raw_lines[i - 2].rstrip()
                    if prev2 == "":
                        ok_prev = True
                    elif _is_adornment_line(prev2):
                        # パターン B のアンダーラインを既にこのループで処理済みのケースは
                        # ここに来ないため、別セクションの adornment と見なしてよい
                        ok_prev = True

                if ok_prev:
                    title_text = title_line.strip()
                    width = _display_width(title_text)
                    under_char = _adornment_char(stripped)
                    under_len = _adornment_length(stripped)
                    if under_len != width:
                        line_num = i + 1
                        violations.append(
                            Violation(
                                line=line_num,
                                kind="セクション下線",
                                text=(
                                    f"title=({title_text})(width={width}) "
                                    f"under='{under_char}'(len={under_len}) -> '{under_char}'*{width}"
                                ),
                            )
                        )
                        fix_plan[i] = (under_char, width)

        i += 1

    return violations, fix_plan


def _atomic_write(filepath: Path, content: str) -> None:
    """tempfile + os.replace による原子的な書き込み。

    書き込み中の中断によるファイル破損を回避する。同じディレクトリに一時ファイルを作成し、
    書き込み完了後に ``os.replace`` でリネームする。
    元ファイルのパーミッション（モードビット下位 9 桁）を取得できた場合は、 ``os.replace`` 直前に
    一時ファイルへ復元することで mkstemp の既定 0600 から元の権限を引き継ぐ。 ``stat`` 自体に
    失敗した場合（元ファイル不在等）は復元をスキップして警告ログを残す。
    """
    original_mode: int | None = None
    try:
        original_mode = filepath.stat().st_mode & 0o777
    except OSError as e:
        logger.warning(f"パーミッション取得失敗（既定値で書き込みます）: {filepath}: {e}")

    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(filepath.parent),
        prefix=f".{filepath.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fp:
            fp.write(content)
        if original_mode is not None:
            try:
                os.chmod(tmp_path, original_mode)
            except OSError as e:
                logger.warning(f"パーミッション復元失敗（既定値で書き込みます）: {filepath}: {e}")
        os.replace(tmp_path, filepath)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _analyze(text: str) -> tuple[list[Violation], dict[int, tuple[str, int]], list[str]]:
    """テキストを解析し (違反リスト, 修正計画, raw_lines) を返す。"""
    raw_lines = text.splitlines(keepends=True)
    skip_mask = build_skip_mask(raw_lines)
    violations, fix_plan = _detect_violations(raw_lines, skip_mask)
    return violations, fix_plan, raw_lines


def _apply_fix_plan(raw_lines: list[str], fix_plan: dict[int, tuple[str, int]]) -> list[str]:
    """修正計画を適用した行リストを返す（改行コード保持）。"""
    fixed_lines = list(raw_lines)
    for line_idx in sorted(fix_plan.keys(), reverse=True):
        fix_char, width = fix_plan[line_idx]
        original = fixed_lines[line_idx]
        if original.endswith("\r\n"):
            newline = "\r\n"
        elif original.endswith("\n"):
            newline = "\n"
        else:
            newline = ""
        fixed_lines[line_idx] = fix_char * width + newline
    return fixed_lines


def find_violations(text: str) -> list[Violation]:
    """テキスト全体の下線・上下線違反を返す。"""
    return _analyze(text)[0]


def fix_text(text: str) -> str:
    """違反を修正した全文を返す（冪等）。"""
    violations, fix_plan, raw_lines = _analyze(text)
    if not fix_plan:
        return text
    return "".join(_apply_fix_plan(raw_lines, fix_plan))


def check_file(
    filepath: Path,
    *,
    fix: bool = False,
    diff: bool = False,
    backup_suffix: str | None = None,
) -> tuple[list[Violation], list[str], bool] | None:
    """1 ファイルを検査し、違反リスト・unified diff 行・書き込み失敗フラグを返す。

    ``fix=True`` の場合はファイルを修正する。``diff=True`` の場合は修正後の内容との
    unified diff を生成し、ファイルは変更しない。``fix`` と ``diff`` は同時指定不可。

    バックアップ作成（``backup_suffix`` 指定時）または ``_atomic_write`` の書き込みが
    ``OSError`` で失敗した場合は、ファイル変更を中止して書き込み失敗フラグ True を返す。

    Returns:
        (violations, diff_lines, write_failed)。読み取りに失敗した場合は None。
        diff_lines は ``diff=True`` のときのみ unified diff 行のリスト、それ以外は空リスト。
        write_failed は ``fix=True`` でバックアップまたは書き込みに失敗した場合のみ True。
    """
    assert not (fix and diff)

    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f"読み取りエラー: {filepath}: {e}")
        return None

    violations, fix_plan, raw_lines = _analyze(text)

    diff_lines: list[str] = []
    write_failed = False

    if diff and fix_plan:
        fixed_lines = _apply_fix_plan(raw_lines, fix_plan)
        diff_lines = list(
            difflib.unified_diff(
                raw_lines,
                fixed_lines,
                fromfile=str(filepath),
                tofile=f"{filepath} (fixed)",
                n=3,
            )
        )

    if fix and fix_plan:
        if backup_suffix is not None:
            backup_path = filepath.with_name(filepath.name + backup_suffix)
            try:
                shutil.copy2(filepath, backup_path)
            except OSError as e:
                logger.error(f"バックアップ作成失敗（修正をスキップ）: {filepath} -> {backup_path}: {e}")
                return violations, diff_lines, True

        # 後ろから順に書き換えてオフセットずれを防ぐ
        fixed_lines = _apply_fix_plan(raw_lines, fix_plan)
        try:
            _atomic_write(filepath, "".join(fixed_lines))
        except OSError as e:
            logger.error(f"書き込みエラー: {filepath}: {e}")
            write_failed = True

    return violations, diff_lines, write_failed


def run(
    paths: list[Path],
    *,
    fix: bool,
    diff: bool,
    backup_suffix: str | None,
    follow_symlinks: bool,
) -> int:
    """メイン処理。

    Returns:
        終了コード（0: 違反なしまたは修正成功, 1: 違反検出 / 読み取りエラー / 書き込みエラー / ファイル無し）
    """
    setup_logging()
    rst_files = collect_rst_files_pruned(paths, follow_symlinks=follow_symlinks, logger=logger)

    if not rst_files:
        logger.error("エラー: .rst ファイルが見つかりませんでした")
        return 1

    log_header(logger, len(rst_files))

    total_violations = 0
    read_errors = 0
    write_errors = 0

    for filepath in rst_files:
        result = check_file(
            filepath,
            fix=fix,
            diff=diff,
            backup_suffix=backup_suffix,
        )
        if result is None:
            read_errors += 1
            continue
        violations, diff_lines, write_failed = result
        if violations:
            for v in violations:
                logger.info(f"{filepath}:{v.line}: {v.kind}: {v.text}")
            total_violations += len(violations)
        if write_failed:
            write_errors += 1
        if diff and diff_lines:
            for diff_line in diff_lines:
                logger.info(diff_line.rstrip("\n"))

    logger.info(SEPARATOR)
    if read_errors > 0:
        logger.info(f"読み取りエラー: {read_errors} ファイル")
    if write_errors > 0:
        logger.info(f"書き込みエラー: {write_errors} ファイル")

    # サマリ出力（6 パターン）
    if total_violations > 0:
        if fix:
            if write_errors > 0:
                logger.info(f"修正結果: {total_violations} 件中 {write_errors} 件で書き込みエラーが発生しました")
            else:
                logger.info(f"修正結果: {total_violations} 件を修正しました")
        elif diff:
            logger.info(f"検出結果: {total_violations} 件の修正提案を表示しました")
        else:
            logger.info(f"検出結果: {total_violations} 件の違反が見つかりました")
    else:
        if fix:
            logger.info("修正対象はありませんでした")
        elif diff:
            logger.info("修正提案はありませんでした")
        else:
            logger.info("検出結果: 違反はありません")

    # 終了コード判定
    if read_errors > 0 or write_errors > 0:
        return 1
    if total_violations > 0:
        if fix:
            return 0
        return 1
    return 0
