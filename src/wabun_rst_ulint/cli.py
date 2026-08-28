"""wabun-rst-ulint CLI エントリポイント。

4 つのサブコマンド（inline-spacing / strong-spacing / heading-width /
sentence-breaks）を argparse サブパーサで提供する。全サブコマンド共通で
--check / --fix は相互排他、フラグなし＝検査（--check と同義）。
heading-width のみ --diff / --backup-suffix / --follow-symlinks を持つ
（バリデーションは元スクリプトの parse_args と同一文言）。
sentence-breaks は --follow-symlinks を持ち、I/O エラー時は終了コード 2 を返す。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def _add_paths_argument(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument("paths", nargs="+", type=Path, help=help_text)


def _add_check_fix_group(parser: argparse.ArgumentParser, *, fix_help: str) -> argparse._MutuallyExclusiveGroup:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="検出のみ（既定。違反があれば終了コード 1）")
    group.add_argument("--fix", action="store_true", help=fix_help)
    return group


_DIR_HELP = "検査対象のファイルまたはディレクトリ（ディレクトリの場合は .rst を再帰検索）"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wabun-rst-ulint",
        description="reStructuredText ドキュメントの検査・修正 CLI ツール",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    p = subparsers.add_parser(
        "inline-spacing",
        help="インライン記法の外部境界スペースを検出・修正する",
        description=(
            "reStructuredText のインライン記法（インラインリテラル・role 参照・参照・"
            "内部ターゲット・interpreted text）の外部境界スペースを検出・修正する"
        ),
    )
    _add_paths_argument(p, _DIR_HELP)
    _add_check_fix_group(p, fix_help="検出された外部境界スペースの不正を自動修正する")

    p = subparsers.add_parser(
        "strong-spacing",
        help="強調表示 (**...**) 前後のスペース不足を検出・修正する",
        description=(
            "reStructuredText の強調表示 (**...**) 前後のスペース不足を検出・修正する。"
            "strong emphasis (**...**) のみを対象とし、単一アスタリスクの emphasis (*...*) は対象外"
        ),
    )
    _add_paths_argument(p, _DIR_HELP)
    _add_check_fix_group(p, fix_help="検出されたスペース不足を自動修正する")

    p = subparsers.add_parser(
        "heading-width",
        help="セクションタイトル下線・上下線の表示幅不一致を検出・修正する",
        description="reStructuredText のセクションタイトル下線・上下線の表示幅不一致を検出・修正する",
    )
    _add_paths_argument(p, _DIR_HELP)
    mode_group = _add_check_fix_group(p, fix_help="検出された下線・上下線を自動修正する（in-place 書き換え）")
    mode_group.add_argument(
        "--diff",
        action="store_true",
        help="修正案を unified diff 形式で標準エラー出力に表示する（書き換えしない）。--check / --fix と排他",
    )
    p.add_argument(
        "--backup-suffix",
        type=str,
        default=None,
        help="--fix 前に shutil.copy2 でバックアップを作成する際の拡張子（例: .bak）。--fix と併用必須",
    )
    p.add_argument(
        "--follow-symlinks",
        action="store_true",
        help=(
            "シンボリックリンクを検査対象に含める（既定では警告とともにスキップ）。"
            "--fix とは併用不可（リンク先実体への意図しない書き込みを防止するため）"
        ),
    )

    p = subparsers.add_parser(
        "sentence-breaks",
        help="「句点と改行」ルールを検出・修正する",
        description="RST の「句点と改行」ルールを検出・修正する",
    )
    _add_paths_argument(p, _DIR_HELP)
    _add_check_fix_group(p, fix_help="ファイルを修正する")
    p.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="シンボリックリンクを検査対象に含める（既定ではスキップ）",
    )

    return parser


def _validate_heading_width(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """元スクリプトの parse_args と同一のバリデーション（文言も同一）。"""
    if args.backup_suffix is not None and not args.fix:
        parser.error("--backup-suffix は --fix と併用してください")
    if args.backup_suffix is not None:
        if args.backup_suffix == "":
            parser.error("--backup-suffix には空でない文字列を指定してください")
        forbidden = ("/", "\\", "..", os.sep)
        if any(token in args.backup_suffix for token in forbidden):
            parser.error("--backup-suffix にパスセパレータや '..' は使用できません")
    if args.fix and args.follow_symlinks:
        parser.error("--fix と --follow-symlinks は併用できません（リンク先実体への書き込みが意図と異なるため）")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # チェッカーは選択されたサブコマンドの分岐内で import する。
    # 使わないチェッカーの import コスト（docutils 依存等）を
    # 他のサブコマンド起動時に払わないため
    if args.subcommand == "inline-spacing":
        from wabun_rst_ulint.checkers import inline_spacing

        return inline_spacing.run(args.paths, fix=args.fix)
    if args.subcommand == "strong-spacing":
        from wabun_rst_ulint.checkers import strong_emphasis_spacing

        return strong_emphasis_spacing.run(args.paths, fix=args.fix)
    if args.subcommand == "heading-width":
        from wabun_rst_ulint.checkers import section_underline

        _validate_heading_width(parser, args)
        return section_underline.run(
            args.paths,
            fix=args.fix,
            diff=args.diff,
            backup_suffix=args.backup_suffix,
            follow_symlinks=args.follow_symlinks,
        )
    if args.subcommand == "sentence-breaks":
        from wabun_rst_ulint.checkers import sentence_breaks

        return sentence_breaks.run(args.paths, fix=args.fix, follow_symlinks=args.follow_symlinks)
    raise AssertionError(f"未知のサブコマンド: {args.subcommand}")
