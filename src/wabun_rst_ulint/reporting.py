"""ログ設定・違反表現・共通ヘッダ出力。

各チェッカーのサマリ分岐（検出結果/修正結果の文言差）は元スクリプトごとに
異なるため共通化せず、各チェッカーの run() が持つ。ここは真に同一の部分のみ。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

SEPARATOR = "-" * 60


@dataclass(frozen=True)
class Violation:
    """検出した違反 1 件。text は行テキストまたは組み立て済み詳細メッセージ。"""

    line: int
    kind: str
    text: str = ""


def setup_logging() -> None:
    """元スクリプトと同一の logging 設定（メッセージのみ・INFO）。"""
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def log_header(logger: logging.Logger, count: int) -> None:
    """検査対象ファイル数のヘッダと区切り線を出力する。"""
    logger.info(f"検査対象: {count} ファイル")
    logger.info(SEPARATOR)
