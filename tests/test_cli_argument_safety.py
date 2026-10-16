"""引数エラーが実ファイルを変更しないことを守る回帰テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from wabun_rst_ulint.cli import main


@pytest.mark.parametrize(
    ("command", "text"),
    [
        ("inline-spacing", "値は``foo``です\n"),
        ("strong-spacing", "本文**重要**です\n"),
        ("heading-width", "見出し\n====\n"),
        ("sentence-breaks", "一文目。二文目\n"),
    ],
)
@pytest.mark.parametrize("flags", [("--check", "--fix"), ("--fix", "--check")])
def test_conflicting_modes_leave_files_unchanged(
    command: str, text: str, flags: tuple[str, str], tmp_path: Path
) -> None:
    original = text.encode("utf-8")
    control = tmp_path / "control.rst"
    control.write_bytes(original)
    # 修正可能な入力を使う。不変の理由が「違反がない」にならないようにする。
    assert main([command, "--fix", str(control)]) == 0
    assert control.read_bytes() != original

    targets = [tmp_path / "日本語 資料.rst", tmp_path / "追加資料.rst"]
    for target in targets:
        target.write_bytes(original)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    with pytest.raises(SystemExit) as excinfo:
        main([command, *flags, *(str(target) for target in targets)])

    assert excinfo.value.code == 2
    # bytes の変更だけでなく、backup などの新しいファイルも検出する。
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
