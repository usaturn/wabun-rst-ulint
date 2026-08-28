"""Frozen inline-repair corpus package (S1 contract data)."""

from __future__ import annotations

from tests.inline_corpus import (
    issue_4,
    issue_5,
    issue_6,
    parity_main,
    review_regressions,
    review_s2_round2,
    review_s2_round3,
    review_s2_round4,
    review_s2_round5,
)
from tests.inline_corpus.cases import (
    DECISIONS,
    RUNTIME_SEMANTICS,
    CorpusValidationError,
    InlineCorpusCase,
    catalog_cases,
    origin_is_resolvable,
    validate_case,
    validate_corpus,
)


def all_cases() -> list[InlineCorpusCase]:
    """Aggregate every corpus module in a stable order."""
    cases: list[InlineCorpusCase] = []
    cases.extend(catalog_cases())
    cases.extend(issue_4.cases())
    cases.extend(issue_5.cases())
    cases.extend(issue_6.cases())
    cases.extend(review_regressions.cases())
    cases.extend(parity_main.cases())
    cases.extend(review_s2_round2.cases())
    cases.extend(review_s2_round3.cases())
    cases.extend(review_s2_round4.cases())
    cases.extend(review_s2_round5.cases())
    return cases


def validated_cases() -> list[InlineCorpusCase]:
    """Return the full corpus after contract validation."""
    return validate_corpus(all_cases())


__all__ = [
    "DECISIONS",
    "RUNTIME_SEMANTICS",
    "CorpusValidationError",
    "InlineCorpusCase",
    "all_cases",
    "catalog_cases",
    "origin_is_resolvable",
    "validate_case",
    "validate_corpus",
    "validated_cases",
]
