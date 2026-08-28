from __future__ import annotations

from pathlib import Path

import pytest

from tests.inline_corpus import validated_cases
from wabun_rst_ulint.checkers import inline_spacing
from wabun_rst_ulint.checkers._inline_classifier import classify_document
from wabun_rst_ulint.cli import build_parser, main

REPO_ROOT = Path(__file__).resolve().parents[1]
RECOMMENDED_ORDER = ("sentence-breaks", "inline-spacing", "strong-spacing", "heading-width")
ALTERNATE_ORDER = ("inline-spacing", "strong-spacing", "sentence-breaks", "heading-width")
TRANSACTION_CASE_ID = "control.combined_proof.rejection"


def _safe_name(case_id: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in case_id)


def _materialize_corpus(
    tmp_path: Path,
    *,
    exclude: set[str] | None = None,
) -> tuple[Path, dict[str, Path]]:
    tree = tmp_path / "corpus"
    tree.mkdir()
    excluded = exclude or set()
    paths: dict[str, Path] = {}
    for index, case in enumerate(validated_cases()):
        if case.id in excluded:
            continue
        path = tree / f"{index:03d}-{_safe_name(case.id)}.rst"
        path.write_text(case.source, encoding="utf-8")
        paths[case.id] = path
    return tree, paths


def _snapshot_tree(tree: Path) -> dict[str, bytes]:
    return {path.relative_to(tree).as_posix(): path.read_bytes() for path in sorted(tree.rglob("*.rst"))}


def _run_fix_sequence(tree: Path, commands: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(main([command, "--fix", str(tree)]) for command in commands)


def test_ci_pins_python_docutils_and_all_release_commands():
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'python-version: "3.14"' in workflow
    assert "docutils==0.22.4" in workflow
    assert 'import docutils; assert docutils.__version__ == "0.22.4"' in workflow
    for command in (
        "pytest -q",
        "uvx ruff check src tests",
        "uvx ruff format --check src tests",
        # A bare `git diff --check` is vacuous after checkout: the tree is clean and no
        # earlier step writes to it. Only the range form against the PR base can fail.
        "git diff --check ${{ github.event.pull_request.base.sha }}...HEAD",
    ):
        assert command in workflow
    assert "fetch-depth: 0" in workflow
    assert "if: github.event_name == 'pull_request'" in workflow


def test_full_corpus_runs_through_final_cli(tmp_path: Path):
    tree, paths = _materialize_corpus(tmp_path, exclude={TRANSACTION_CASE_ID})
    assert len(paths) == 126
    before = _snapshot_tree(tree)
    assert main(["inline-spacing", "--check", str(tree)]) == 1
    assert _snapshot_tree(tree) == before
    assert main(["inline-spacing", "--fix", str(tree)]) == 0
    first = _snapshot_tree(tree)
    assert main(["inline-spacing", "--fix", str(tree)]) == 0
    # The bounded-convergence exception is restricted to three interaction.* ids, none of
    # which is in this corpus, so pass 1 must already be the fixed point. A corpus case
    # that drifts into two-pass behaviour turns this red.
    assert _snapshot_tree(tree) == first
    assert main(["inline-spacing", "--check", str(tree)]) == 0
    assert first != before


def test_full_corpus_case_count_is_frozen():
    cases = validated_cases()
    assert len(cases) == 127
    # 55 -> 57 at Issue #22: two parity rows moved from unchanged to must_fix.
    # The row count is unchanged; only their declared decision moved.
    assert sum(case.must_fix for case in cases) == 57


STRONG_MUST_FIX_IDS = frozenset(
    {
        "issue4.outer-strong-boundary.repairable",
        "issue6.outer-strong-with-literal.missing-boundaries",
        "issue6.outer-strong-with-role.missing-boundaries",
    }
)


def test_all_must_fix_cases_reach_declared_output_through_owner_command(tmp_path: Path):
    cases = [case for case in validated_cases() if case.must_fix]
    assert len(cases) == 57
    for case in cases:
        target = tmp_path / f"{_safe_name(case.id)}.rst"
        target.write_text(case.source, encoding="utf-8")
        command = "strong-spacing" if case.id in STRONG_MUST_FIX_IDS else "inline-spacing"
        assert main([command, "--fix", str(target)]) == 0
        assert target.read_text(encoding="utf-8") == case.expected


def test_all_must_fix_cases_have_a_supported_owner():
    cases = [case for case in validated_cases() if case.must_fix]
    assert len(cases) == 57
    for case in cases:
        views = classify_document(case.source)
        if case.id in STRONG_MUST_FIX_IDS:
            assert views.strong.owners, case.id
        else:
            accepted = [decision for decision in views.inline.decisions if decision.status == "accepted"]
            assert accepted, case.id


def test_combined_proof_failure_is_no_write_diagnostic_exit_1(tmp_path: Path, capsys, monkeypatch):
    target = tmp_path / "combined-proof.rst"
    target.write_text("値は``foo``です\n", encoding="utf-8")
    before = target.read_bytes()

    real_build = inline_spacing.build_document_fingerprint

    def rejecting_build(source: str, *, edit_ranges=(), message_aliases=()):
        fingerprint = real_build(source, edit_ranges=edit_ranges, message_aliases=message_aliases)
        return inline_spacing.DocumentFingerprint(
            untouched_inlines=fingerprint.untouched_inlines + (("literal", "``corrupted``", "corrupted"),),
            blocks=fingerprint.blocks,
            messages=fingerprint.messages,
            truncated_from_line=fingerprint.truncated_from_line,
        )

    monkeypatch.setattr(inline_spacing, "build_document_fingerprint", rejecting_build)

    assert main(["inline-spacing", "--fix", str(target)]) == 1
    captured = capsys.readouterr()
    assert target.read_bytes() == before
    assert "修正失敗（変更なし）" in captured.err
    assert "combined projection proof failed" in captured.err


@pytest.fixture
def representative_source() -> str:
    return "見出し\n====\n\n一文目。値は:term:`X`と``code``です。本文**a``lit``b**です。\n"


def test_recommended_four_command_third_round_is_noop(tmp_path: Path, representative_source: str):
    tree = tmp_path / "recommended"
    tree.mkdir()
    (tree / "representative.rst").write_text(representative_source, encoding="utf-8")
    assert all(code == 0 for code in _run_fix_sequence(tree, RECOMMENDED_ORDER))
    first = _snapshot_tree(tree)
    assert all(code == 0 for code in _run_fix_sequence(tree, RECOMMENDED_ORDER))
    second = _snapshot_tree(tree)
    assert second != first
    assert all(code == 0 for code in _run_fix_sequence(tree, RECOMMENDED_ORDER))
    assert _snapshot_tree(tree) == second


def test_full_corpus_recommended_order_reaches_its_fixed_point_in_one_round(tmp_path: Path):
    tree, paths = _materialize_corpus(tmp_path, exclude={TRANSACTION_CASE_ID})
    assert len(paths) == 126
    assert all(code == 0 for code in _run_fix_sequence(tree, RECOMMENDED_ORDER))
    first = _snapshot_tree(tree)
    assert all(code == 0 for code in _run_fix_sequence(tree, RECOMMENDED_ORDER))
    second = _snapshot_tree(tree)
    # No corpus case needs a second round; only the three allowlisted interaction.* ids do,
    # and none of them is in the corpus. Rounds 2 and 3 must both be no-ops.
    assert second == first
    assert all(code == 0 for code in _run_fix_sequence(tree, RECOMMENDED_ORDER))
    assert _snapshot_tree(tree) == second


def test_sentence_inline_strong_alternate_order_reaches_same_fixed_point(tmp_path: Path, representative_source: str):
    recommended = tmp_path / "recommended"
    alternate = tmp_path / "alternate"
    recommended.mkdir()
    alternate.mkdir()
    (recommended / "representative.rst").write_text(representative_source, encoding="utf-8")
    (alternate / "representative.rst").write_text(representative_source, encoding="utf-8")

    for _ in range(3):
        assert all(code == 0 for code in _run_fix_sequence(recommended, RECOMMENDED_ORDER))
        assert all(code == 0 for code in _run_fix_sequence(alternate, ALTERNATE_ORDER))
    assert _snapshot_tree(recommended) == _snapshot_tree(alternate)


def test_public_cli_exposes_exactly_four_commands():
    parser = build_parser()
    subparser_action = next(action for action in parser._actions if getattr(action, "choices", None))
    assert tuple(subparser_action.choices) == (
        "inline-spacing",
        "strong-spacing",
        "heading-width",
        "sentence-breaks",
    )


@pytest.mark.parametrize(
    "legacy",
    (
        "literal-spacing",
        "role-spacing",
        "role-visible-spacing",
        "inline-markup",
        "section-underline",
        "kuten",
    ),
)
def test_legacy_commands_are_rejected_with_argparse_exit_2(legacy: str):
    with pytest.raises(SystemExit) as exc_info:
        main([legacy, "unused.rst"])
    assert exc_info.value.code == 2
