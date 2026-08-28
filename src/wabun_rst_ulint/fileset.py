""".rst ファイル収集の 2 バリアント。

- collect_rst_files: inline-spacing / strong-spacing 用（警告スキップ・除外なし）
- collect_rst_files_pruned: heading-width / sentence-breaks 用（symlink 制御・管理外ディレクトリ除外）

挙動差は元スクリプトの意図的な差異であり統一しない。
2 バリアントとも、返却前に初出順を保って重複パスを除去する。
"""

import logging
from collections.abc import Callable
from pathlib import Path

# 再帰検索時に除外する管理外ディレクトリ名
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "__pycache__",
        "node_modules",
        "_build",
        ".aws-sam",
        ".cache",
    }
)


def _deduplicate(paths: list[Path]) -> list[Path]:
    """初出順を保って重複パスを除去する。resolve() で正規化して比較する。"""
    seen: dict[Path, Path] = {}
    for p in paths:
        key = p.resolve()
        if key not in seen:
            seen[key] = p
    return list(seen.values())


def collect_rst_files(paths: list[Path], warn: Callable[[str], None]) -> list[Path]:
    """指定されたパスから .rst ファイルを収集する。

    警告の出力先は ``warn`` コールバックで注入する（spacing 系は logger.warning）。
    """
    rst_files: list[Path] = []
    for path in paths:
        if path.is_file():
            if path.suffix == ".rst":
                rst_files.append(path)
            else:
                warn(f"スキップ: {path}（.rst ファイルではありません）")
        elif path.is_dir():
            rst_files.extend(sorted(path.rglob("*.rst")))
        else:
            warn(f"スキップ: {path}（存在しません）")
    # 引数の重なり（ディレクトリ + 配下ファイル等）による二重処理を防ぐ。初出順を保つ
    return _deduplicate(rst_files)


def collect_rst_files_pruned(paths: list[Path], *, follow_symlinks: bool, logger: logging.Logger) -> list[Path]:
    """指定されたパスから .rst ファイルを収集する。

    ディレクトリ指定の場合、 ``EXCLUDED_DIR_NAMES`` に含まれるディレクトリ配下のファイルは除外する。
    ただし、ユーザーが ``.venv`` 等の管理外ディレクトリ名を引数で直接指定した場合は除外せず、
    その明示的指定を尊重して再帰検索の起点として扱う（除外判定は再帰結果の相対パス上のみで行う）。
    シンボリックリンクは ``follow_symlinks=False`` のとき警告付きでスキップする。
    """
    rst_files: list[Path] = []
    for path in paths:
        if path.is_file():
            if path.is_symlink() and not follow_symlinks:
                logger.warning(f"スキップ: {path}（シンボリックリンクです。--follow-symlinks で許可可）")
                continue
            if path.suffix == ".rst":
                rst_files.append(path)
            else:
                logger.warning(f"スキップ: {path}（.rst ファイルではありません）")
        elif path.is_dir():
            if path.is_symlink() and not follow_symlinks:
                logger.warning(f"スキップ: {path}（シンボリックリンクです。--follow-symlinks で許可可）")
                continue
            candidates: list[Path] = []
            for candidate in sorted(path.rglob("*.rst")):
                relative_parts = set(candidate.relative_to(path).parts)
                if relative_parts & EXCLUDED_DIR_NAMES:
                    continue
                if candidate.is_symlink() and not follow_symlinks:
                    logger.warning(f"スキップ: {candidate}（シンボリックリンクです。--follow-symlinks で許可可）")
                    continue
                candidates.append(candidate)
            rst_files.extend(candidates)
        else:
            logger.warning(f"スキップ: {path}（存在しません）")
    # 引数の重なり（ディレクトリ + 配下ファイル等）による二重処理を防ぐ。初出順を保つ
    return _deduplicate(rst_files)
