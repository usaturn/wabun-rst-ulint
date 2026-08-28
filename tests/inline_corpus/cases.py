"""Frozen InlineCorpusCase schema, validation, and supported-repair catalog."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

Decision = Literal["unchanged", "repairable", "diagnostic-only"]

DECISIONS: frozenset[str] = frozenset({"unchanged", "repairable", "diagnostic-only"})

REPO_ROOT = Path(__file__).resolve().parents[2]
GITHUB_ORIGIN_PREFIX = "https://github.com/usaturn/urst-checker/"

# Runtime meaning encoded for schema tests (S1 does not implement production).
RUNTIME_SEMANTICS: dict[str, dict[str, object]] = {
    "unchanged": {
        "must_fix_allowed": frozenset({False}),
        "check_reports_violation": False,
        "fix_writes": False,
        "exit_effect": "neutral",
    },
    "repairable": {
        "must_fix_allowed": frozenset({True, False}),
        "check_reports_violation": True,
        "fix_writes": True,  # successful fix only; combined-proof failure is exit-1 no-write
        "exit_effect": "check=1; successful_fix=0; combined_proof_failure=1",
    },
    "diagnostic-only": {
        "must_fix_allowed": frozenset({False}),
        "check_reports_violation": False,  # non-fixing warning, not a check failure
        "fix_writes": False,
        "exit_effect": "neutral",
        "emits_warning": True,
    },
}


@dataclass(frozen=True)
class InlineCorpusCase:
    """One frozen inline-repair contract case."""

    id: str
    source: str
    decision: Decision
    must_fix: bool
    expected: str | None
    origin: str
    notes: str = ""


class CorpusValidationError(ValueError):
    """Raised when corpus data violates the S1 contract."""


def _tracked_paths() -> set[str]:
    """Paths tracked by git at REPO_ROOT (relative posix)."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def origin_is_resolvable(origin: str, *, tracked: set[str] | None = None) -> bool:
    """True if origin is a project GitHub URL or a tracked repository path."""
    if origin.startswith(GITHUB_ORIGIN_PREFIX):
        return len(origin) > len(GITHUB_ORIGIN_PREFIX)
    # Reject ignored reviews-only provenance
    if origin.startswith("reviews/") or "/reviews/" in origin:
        return False
    paths = tracked if tracked is not None else _tracked_paths()
    normalized = origin.replace("\\", "/").lstrip("./")
    if normalized in paths:
        return True
    # Allow absolute-within-repo style
    try:
        rel = Path(origin).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError, OSError:
        return False
    return rel in paths


def validate_case(case: InlineCorpusCase, *, tracked: set[str] | None = None) -> None:
    """Validate a single case; raise CorpusValidationError on contract breach."""
    if not case.id:
        raise CorpusValidationError("case id must be non-empty")
    if case.decision not in DECISIONS:
        raise CorpusValidationError(f"{case.id}: decision must be one of {sorted(DECISIONS)}, got {case.decision!r}")
    if case.decision == "repairable":
        if case.expected is None:
            raise CorpusValidationError(f"{case.id}: repairable cases require expected output")
    if case.must_fix and case.decision == "unchanged":
        raise CorpusValidationError(f"{case.id}: must_fix=True is incompatible with unchanged")
    if case.must_fix and case.decision == "diagnostic-only":
        raise CorpusValidationError(f"{case.id}: must_fix=True is incompatible with diagnostic-only")
    if case.decision == "diagnostic-only" and case.must_fix:
        raise CorpusValidationError(f"{case.id}: diagnostic-only forbids must_fix")
    if not origin_is_resolvable(case.origin, tracked=tracked):
        raise CorpusValidationError(f"{case.id}: origin is not resolvable: {case.origin!r}")


def validate_corpus(cases: Iterable[InlineCorpusCase], *, tracked: set[str] | None = None) -> list[InlineCorpusCase]:
    """Validate all cases; ensure unique IDs; return the list."""
    path_set = tracked if tracked is not None else _tracked_paths()
    seen: set[str] = set()
    out: list[InlineCorpusCase] = []
    for case in cases:
        if case.id in seen:
            raise CorpusValidationError(f"duplicate corpus id: {case.id}")
        seen.add(case.id)
        validate_case(case, tracked=path_set)
        out.append(case)
    return out


def _o(path: str) -> str:
    """GitHub blob origin for catalog design doc rows (tracked plan path)."""
    return f"{GITHUB_ORIGIN_PREFIX}blob/f595d71/{path}"


def catalog_cases() -> list[InlineCorpusCase]:
    """Supported repair catalog + explicit no-touch / boundary controls."""
    plan = "docs/superpowers/plans/2026-08-03-clean-slate-inline-spacing.md"
    # Prefer GitHub URL origin so ignored docs/superpowers still resolves.
    origin = f"{GITHUB_ORIGIN_PREFIX}issues/9"
    cases: list[InlineCorpusCase] = [
        # --- inline literal ---
        InlineCorpusCase(
            id="catalog.literal.ja-adjacent",
            source="値は``foo``です\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo`` です\n",
            origin=origin,
            notes="supported form: inline literal; Japanese adjacency",
        ),
        InlineCorpusCase(
            id="catalog.literal.ascii-adjacent",
            source="value is``foo``here\n",
            decision="repairable",
            must_fix=True,
            expected="value is ``foo`` here\n",
            origin=origin,
            notes="supported form: inline literal; ASCII adjacency",
        ),
        InlineCorpusCase(
            id="catalog.literal.punct-adjacent",
            source="見よ``foo``。\n",
            decision="repairable",
            must_fix=True,
            expected="見よ ``foo``。\n",
            origin=origin,
            notes="supported form: inline literal; punctuation adjacency (after may be punct)",
        ),
        InlineCorpusCase(
            id="catalog.literal.tab-boundary",
            source="値は\t``foo``\tです\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo`` です\n",
            origin=origin,
            notes="tab at editable external boundary normalizes to ASCII space",
        ),
        InlineCorpusCase(
            id="catalog.literal.nbsp-boundary",
            source="値は\u00a0``foo``\u00a0です\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo`` です\n",
            origin=origin,
            notes="NBSP at editable external boundary normalizes to ASCII space",
        ),
        InlineCorpusCase(
            id="catalog.literal.ideographic-boundary",
            source="値は\u3000``foo``\u3000です\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo`` です\n",
            origin=origin,
            notes="ideographic space at editable external boundary → ASCII space",
        ),
        InlineCorpusCase(
            id="catalog.literal.valid-unchanged",
            source="値は ``foo`` です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="already valid literal spacing",
        ),
        # --- prefix role ---
        InlineCorpusCase(
            id="catalog.role.prefix.ja-adjacent",
            source="用語:term:`SCIM`同期\n",
            decision="repairable",
            must_fix=True,
            expected="用語 :term:`SCIM` 同期\n",
            origin=origin,
            notes="supported form: prefix role; Japanese adjacency",
        ),
        InlineCorpusCase(
            id="catalog.role.prefix.fullwidth-paren-start",
            source="）:term:`SCIM` 同期\n",
            decision="repairable",
            must_fix=True,
            expected="） :term:`SCIM` 同期\n",
            origin=origin,
            notes="prefix role after fullwidth close paren; visible ASCII space normal form",
        ),
        InlineCorpusCase(
            id="catalog.role.prefix.valid-unchanged",
            source="これは :term:`SCIM` の説明\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="valid prefix role boundaries",
        ),
        # --- postfix role ---
        InlineCorpusCase(
            id="catalog.role.postfix.ja-adjacent",
            source="値は`SCIM`:term:です\n",
            decision="repairable",
            must_fix=True,
            expected="値は `SCIM`:term: です\n",
            origin=origin,
            notes="supported form: postfix role",
        ),
        InlineCorpusCase(
            id="catalog.role.postfix.valid-unchanged",
            source="値は `SCIM`:term: です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="valid postfix role",
        ),
        # --- named / anonymous reference ---
        InlineCorpusCase(
            id="catalog.ref.named.ja-adjacent",
            source="参照`phrase`_直後\n",
            decision="repairable",
            must_fix=True,
            expected="参照 `phrase`_ 直後\n",
            origin=origin,
            notes="supported form: named reference",
        ),
        InlineCorpusCase(
            id="catalog.ref.anonymous.ja-adjacent",
            source="参照`phrase`__直後\n",
            decision="repairable",
            must_fix=True,
            expected="参照 `phrase`__ 直後\n",
            origin=origin,
            notes="supported form: anonymous reference",
        ),
        InlineCorpusCase(
            id="catalog.ref.named.valid-unchanged",
            source="参照 `phrase`_ です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="valid named reference spacing",
        ),
        # --- internal target ---
        InlineCorpusCase(
            id="catalog.target.internal.ja-adjacent",
            source="定義_`target`です\n",
            decision="repairable",
            must_fix=True,
            expected="定義 _`target` です\n",
            origin=origin,
            notes="supported form: internal target",
        ),
        InlineCorpusCase(
            id="catalog.target.internal.valid-unchanged",
            source="定義 _`target` です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="valid internal target",
        ),
        # --- interpreted text (unique ownership only) ---
        InlineCorpusCase(
            id="catalog.interp.unique-owned.ja-adjacent",
            source="名称`API`は重要\n",
            decision="repairable",
            must_fix=True,
            expected="名称 `API` は重要\n",
            origin=origin,
            notes="interpreted text: uniquely owned mandatory context",
        ),
        InlineCorpusCase(
            id="catalog.interp.equal-score-control",
            source="x`a`y`b`z\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="interpreted text equal-score/ambiguous control — no-touch",
        ),
        InlineCorpusCase(
            id="catalog.interp.valid-unchanged",
            source="名称 `API` は重要\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="valid interpreted text spacing",
        ),
        # --- boundary null escape → visible ASCII space ---
        InlineCorpusCase(
            id="catalog.boundary.null-escape-normalize",
            source="）\\ :term:`SCIM` 同期\n",
            decision="repairable",
            must_fix=True,
            expected="） :term:`SCIM` 同期\n",
            origin=origin,
            notes="boundary null escape normalizes to visible ASCII space",
        ),
        # --- no-touch / diagnostic controls ---
        InlineCorpusCase(
            id="catalog.notouch.escaped-literal-shape",
            source="値は\\``foo\\``です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="escaped complete token shape is no-touch",
        ),
        InlineCorpusCase(
            id="catalog.notouch.malformed-backticks",
            source="壊れた`だけ\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="malformed shape — no-touch",
        ),
        InlineCorpusCase(
            id="catalog.notouch.list-marker-prefix",
            source="- ``item`` です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="structural line prefix (bullet) preserved",
        ),
        InlineCorpusCase(
            id="catalog.notouch.option-list-separator",
            source="-a  option describes ``x`` here\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="option-list separator must not be rewritten into structural break",
        ),
        InlineCorpusCase(
            id="catalog.notouch.code-block-body",
            source=".. code-block:: text\n\n   x``y``z\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="code-block body is no-touch",
        ),
        InlineCorpusCase(
            id="catalog.notouch.literal-block-body",
            source="例は ``foo`` のとおり::\n\n   本文``内``は無視\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="literal-block body skipped; trigger line already valid here",
        ),
        InlineCorpusCase(
            id="catalog.notouch.raw-directive-body",
            source=".. raw:: html\n\n   <b>``x``</b>\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="raw directive body opaque/non-editable",
        ),
        InlineCorpusCase(
            id="catalog.notouch.math-directive-body",
            source=".. math::\n\n   a``b``c\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="math directive body no-touch",
        ),
        InlineCorpusCase(
            id="catalog.notouch.mermaid-body",
            source=".. mermaid::\n\n   A[`x`後]\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="mermaid body no-touch",
        ),
        InlineCorpusCase(
            id="catalog.notouch.csv-table-body",
            source=".. csv-table::\n\n   ``a``,``b``\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="csv-table body no-touch",
        ),
        InlineCorpusCase(
            id="catalog.checkable.footnote-body",
            source=".. [1] 注に``x``あり\n",
            decision="repairable",
            must_fix=True,
            expected=".. [1] 注に ``x`` あり\n",
            origin=origin,
            notes="footnote body remains checkable parsed text",
        ),
        InlineCorpusCase(
            id="catalog.checkable.citation-body",
            source=".. [CIT] 文献に``x``あり\n",
            decision="repairable",
            must_fix=True,
            expected=".. [CIT] 文献に ``x`` あり\n",
            origin=origin,
            notes="citation body remains checkable",
        ),
        InlineCorpusCase(
            id="catalog.checkable.substitution-body",
            source=".. |m| replace:: 値は``x``です\n",
            decision="repairable",
            must_fix=True,
            expected=".. |m| replace:: 値は ``x`` です\n",
            origin=origin,
            notes="substitution definition body remains checkable",
        ),
        # --- oracle authority controls ---
        InlineCorpusCase(
            id="control.oracle.note-body-checkable",
            source=".. note::\n\n   値は``x``です\n",
            decision="repairable",
            must_fix=True,
            expected=".. note::\n\n   値は ``x`` です\n",
            origin=origin,
            notes="parsed note body is checkable; oracle authority over pre-filter",
        ),
        InlineCorpusCase(
            id="control.oracle.unknown-directive-opaque",
            source=".. unknown-directive::\n\n   body ``x`` y\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="unknown directive body opaque non-editable",
        ),
        InlineCorpusCase(
            id="control.oracle.sphinx-directive-opaque",
            source=".. py:function:: foo\n\n   body``x``y\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="Sphinx-like directive body opaque without Sphinx",
        ),
        InlineCorpusCase(
            id="control.oracle.include-disabled-opaque",
            source=".. include:: missing.rst\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="disabled include is opaque; no file read",
        ),
        InlineCorpusCase(
            id="control.oracle.raw-disabled-opaque",
            source=".. raw:: html\n\n   <b>x</b>\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="disabled raw is opaque",
        ),
        # --- source-map / alignment controls ---
        InlineCorpusCase(
            id="control.sourcemap.repeated-rawsource",
            source="A ``x`` B ``x`` C\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="one-line repeated identical rawsource for order-preserving alignment",
        ),
        InlineCorpusCase(
            id="control.sourcemap.multiline-paragraph",
            source="第一行 ``a`` です\n第二行 ``b`` です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="multiline paragraph source-map control",
        ),
        InlineCorpusCase(
            id="control.sourcemap.nested-looking-strong-literal",
            source="本文 **``x``** です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="nested-looking **``x``** must remain strong+literal; no false repair",
        ),
        InlineCorpusCase(
            id="control.sourcemap.escaped-backtick",
            source="code uses \\` backtick and ``real`` lit\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="escaped backtick vs real literal",
        ),
        InlineCorpusCase(
            id="control.sourcemap.non-reversible-logical-map",
            source="行1\n\n行2 ``x`` です\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="intentionally non-trivial logical-to-physical mapping fixture",
        ),
        # --- sentence / malformed controls ---
        InlineCorpusCase(
            id="control.sentence.unterminated-inline",
            source="開始だけ`残る\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="unterminated/malformed inline region — no-touch",
        ),
        InlineCorpusCase(
            id="control.sentence.block-ending-literal-kuten",
            source="終わりは ``完了。``\n",
            decision="unchanged",
            must_fix=False,
            expected=None,
            origin=origin,
            notes="block-ending literal whose payload ends with 。",
        ),
        # --- mixed document / combined proof ---
        InlineCorpusCase(
            id="control.mixed.mandatory-plus-unprovable",
            source="値は``foo``ですと x`a`y`b`z 曖昧\n",
            decision="repairable",
            must_fix=True,
            expected="値は ``foo`` ですと x`a`y`b`z 曖昧\n",
            origin=origin,
            notes="mandatory repair coexists with unprovable candidate; unprovable excluded pre-projection",
        ),
        InlineCorpusCase(
            id="control.combined_proof.rejection",
            source="本文 **``重要``** です\n",
            # Not diagnostic-only: transaction/combined-proof failure is exit 1
            # with actionable diagnostic and no write (see RUNTIME_SEMANTICS
            # repairable.combined_proof_failure=1). diagnostic-only is exit-neutral.
            decision="repairable",
            must_fix=False,
            # Only admissible on-disk state after a failed combined proof is the
            # original document (no write). expected==source freezes that contract;
            # a successful non-identity rewrite is not admitted for this fixture.
            expected="本文 **``重要``** です\n",
            origin=origin,
            notes=(
                "combined-proof rejection fixture: naive interior literal boundary "
                "edit would destroy strong; fix path must not write, emit an "
                "actionable diagnostic, and exit 1 (RUNTIME_SEMANTICS repairable "
                "combined_proof_failure=1). Not diagnostic-only (exit-neutral)."
            ),
        ),
    ]
    # silence unused
    del plan
    return cases
