"""パッケージ骨格・依存版数・レガシー名の残存ゲートのテスト。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import wabun_rst_ulint

REPO = Path(__file__).resolve().parents[1]

# Issue #14 で撤去した 6 つのサブコマンド名
LEGACY_COMMAND_NAMES = (
    "literal-spacing",
    "role-spacing",
    "role-visible-spacing",
    "section-underline",
    "inline-markup",
    "kuten",
)

# 意図的に残るレガシー名の出現箇所。仕様の基準は「拒否の証明」または「履歴証拠」であり、
# 各エントリはそのいずれかに該当する。
# - tests/test_cli.py: 6 つの旧名が argparse に拒否されることの証明
# - tests/test_cli_end_to_end.py: 6 つの旧名が argparse に拒否されることの証明
# - tests/test_sentence_breaks_integration.py: 旧 kuten モジュールが import できないことを示す
#   negative assertion。モジュール名そのものがテストの主張である
# - tests/inline_corpus/cases.py: S1 凍結コーパスの case id（「句点」という日本語術語であり、
#   削除済みサブコマンド名ではない）
# - tests/inline_corpus/parity_main.py: 削除済みテストの由来を記録した履歴証拠
# - tests/test_package.py: 本ゲート自身が 6 名を検索語として保持する
ALLOWED_LEGACY_NAME_FILES = frozenset(
    {
        "tests/test_cli.py",
        "tests/test_cli_end_to_end.py",
        "tests/test_sentence_breaks_integration.py",
        "tests/inline_corpus/cases.py",
        "tests/inline_corpus/parity_main.py",
        "tests/test_package.py",
    }
)


def test_package_importable():
    assert wabun_rst_ulint.__doc__ is not None


def test_docutils_requirement_pinned_in_pyproject():
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["dependencies"] == ["docutils>=0.22,<0.23"]
    assert data["project"]["requires-python"] == ">=3.14"


def test_docutils_version_locked_in_uv_lock():
    data = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
    versions = [package["version"] for package in data["package"] if package["name"] == "docutils"]
    assert versions == ["0.22.4"]

    project = next(package for package in data["package"] if package["name"] == "wabun-rst-ulint")
    assert project["metadata"]["requires-dist"] == [{"name": "docutils", "specifier": ">=0.22,<0.23"}]


def test_legacy_command_names_appear_only_in_allowed_files():
    """撤去したコマンド名の残存箇所を、拒否の証明と履歴証拠だけに限定する。"""
    offenders: list[str] = []
    for root in ("src", "tests"):
        for path in sorted((REPO / root).rglob("*.py")):
            relative = path.relative_to(REPO).as_posix()
            if relative in ALLOWED_LEGACY_NAME_FILES:
                continue
            text = path.read_text(encoding="utf-8")
            offenders.extend(f"{relative}: {name}" for name in LEGACY_COMMAND_NAMES if name in text)
    assert offenders == []


def test_removed_checker_modules_are_gone():
    checkers = REPO / "src" / "wabun_rst_ulint" / "checkers"
    for name in (
        "inline_markup.py",
        "literal_spacing.py",
        "role_spacing.py",
        "role_visible_spacing.py",
        "_spacing_common.py",
        "kuten.py",
    ):
        assert not (checkers / name).exists(), name
    assert (checkers / "sentence_breaks.py").exists()
