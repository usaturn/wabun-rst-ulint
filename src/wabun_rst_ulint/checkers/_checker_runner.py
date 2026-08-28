"""spacing 系チェッカー共通の .rst 収集・I/O・終了コードエンジン（Issue #11）。

チェッカー固有の判断（transaction failure の是非等）はここでは行わない。
呼び出し側が `process(text) -> RunOutcome` を注入する。
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from wabun_rst_ulint import fileset
from wabun_rst_ulint.reporting import Violation


@dataclass(frozen=True)
class RunOutcome:
    """1 ファイル分の check/fix 結果。

    check モードでは violations のみ意味を持つ。fix モードでは、
    transaction_failure=True なら無書き込み・diagnostic 必須。
    fixed_text が非 None なら成功した変更として書き込む。
    fixed_text が None かつ transaction_failure=False なら変更なし。
    """

    violations: tuple[Violation, ...]
    fixed_text: str | None = None
    transaction_failure: bool = False
    diagnostic: str | None = None


def _atomic_write(filepath: Path, content: str) -> None:
    """実体と同じ directory の tempfile を使って原子的に書き込む。

    filepath が symlink の場合は link entry を置換せず、解決済み target を置換する。
    途中の I/O 失敗では target の元 bytes を保持する。
    """
    target = filepath.resolve(strict=True)
    original_mode: int | None = None
    try:
        original_mode = target.stat().st_mode & 0o777
    except OSError:
        original_mode = None

    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
        if original_mode is not None:
            os.chmod(tmp_path, original_mode)
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _normalize_newlines(text: str) -> tuple[str, str]:
    """最初の物理改行種別を記録し、CRLF/CR を LF へ正規化する。"""
    first = re.search(r"\r\n|\r|\n", text)
    newline = first.group(0) if first is not None else "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n"), newline


def _restore_newlines(text: str, newline: str) -> str:
    """LF 正規化済みテキストを記録済み改行種別へ戻す。"""
    return text if newline == "\n" else text.replace("\n", newline)


def run_checker(
    paths: list[str],
    *,
    fix: bool,
    process: Callable[[str], RunOutcome],
) -> int:
    """.rst ファイルを収集し、各ファイルに process() を適用して終了コードを返す。

    終了コード: 対象0件=1 / I/Oエラー=1 / check違反あり=1 / fix成功=0 / transaction failure=1
    process には改行を LF へ正規化した文字列を渡す。fixed_text がある場合のみ、
    入力ファイルの改行種別へ戻してから書き込む。
    """
    warnings: list[str] = []
    files = fileset.collect_rst_files([Path(p) for p in paths], warn=warnings.append)
    for message in warnings:
        print(message, file=sys.stderr)

    if not files:
        print("検査対象の .rst ファイルがない", file=sys.stderr)
        return 1

    io_errors = 0
    violation_total = 0
    transaction_failures = 0

    for path in files:
        try:
            with path.open("r", encoding="utf-8", newline="") as fp:
                text = fp.read()
        except (OSError, UnicodeDecodeError) as exc:
            print(f"読み込み失敗: {path}: {exc}", file=sys.stderr)
            io_errors += 1
            continue

        normalized, newline = _normalize_newlines(text)
        outcome = process(normalized)

        if fix:
            if outcome.transaction_failure:
                for violation in outcome.violations:
                    print(f"{path}:{violation.line}: {violation.text}", file=sys.stderr)
                print(f"修正失敗（変更なし）: {path}: {outcome.diagnostic}", file=sys.stderr)
                transaction_failures += 1
                continue
            if outcome.fixed_text is not None:
                try:
                    _atomic_write(path, _restore_newlines(outcome.fixed_text, newline))
                except OSError as exc:
                    print(f"書き込み失敗: {path}: {exc}", file=sys.stderr)
                    io_errors += 1
                    continue
                print(f"修正: {path}（{len(outcome.violations)} 箇所）", file=sys.stderr)
        else:
            if outcome.violations:
                violation_total += len(outcome.violations)
                for v in outcome.violations:
                    print(f"{path}:{v.line}: {v.text}", file=sys.stderr)

    if io_errors:
        return 1
    if fix:
        return 1 if transaction_failures else 0
    return 1 if violation_total else 0
