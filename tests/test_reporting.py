"""reporting モジュールのテスト。"""

import logging

from wabun_rst_ulint.reporting import SEPARATOR, Violation, log_header, setup_logging


def test_violation_fields():
    v = Violation(line=3, kind="前", text="``x``異常")
    assert (v.line, v.kind, v.text) == (3, "前", "``x``異常")


def test_violation_text_default_empty():
    assert Violation(line=1, kind="後").text == ""


def test_separator_is_60_hyphens():
    assert SEPARATOR == "-" * 60


def test_log_header_output(caplog):
    logger = logging.getLogger("test_reporting")
    with caplog.at_level(logging.INFO, logger="test_reporting"):
        log_header(logger, 5)
    assert caplog.messages == ["検査対象: 5 ファイル", SEPARATOR]


def test_setup_logging_idempotent():
    setup_logging()
    setup_logging()  # 2 回呼んでも例外にならない
