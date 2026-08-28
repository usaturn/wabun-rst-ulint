"""Frozen typed inline ownership model for S2 classification (Issue #10).

Independent consumer views replace the shared active/protected boolean model.
These interfaces freeze at S2 completion for S3–S5 consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SourceRange:
    """Physical source span.

    ``start:end`` is a 0-based half-open Python character range.
    ``line`` and ``column`` are 1-based coordinates for ``start``.
    """

    start: int
    end: int
    line: int
    column: int


@dataclass(frozen=True)
class InlineSpan:
    """Docutils-recognized (or opaque-role) inline node with source bounds."""

    source_range: SourceRange
    kind: str
    rawsource: str
    visible_text: str


@dataclass(frozen=True)
class RepairCandidate:
    """Boundary-deficient form admitted by the narrow repair grammar."""

    source_range: SourceRange
    form: str
    expected_rawsource: str


@dataclass(frozen=True)
class StrongOwner:
    """Outer ``**...**`` ownership for strong-spacing.

    Covers both docutils-recognized strong nodes and the narrow
    boundary-deficient outer-strong grammar.
    """

    source_range: SourceRange
    interior_range: SourceRange
    recognized_by_docutils: bool


@dataclass(frozen=True)
class EditDecision:
    """Classifier decision for one repair candidate (no edit applied)."""

    candidate: RepairCandidate
    status: Literal["accepted", "rejected", "unsupported"]
    reason: str


@dataclass(frozen=True)
class InlineView:
    """Independent view for inline-spacing consumers."""

    decisions: tuple[EditDecision, ...]


@dataclass(frozen=True)
class StrongView:
    """Independent view for strong-spacing consumers."""

    owners: tuple[StrongOwner, ...]


@dataclass(frozen=True)
class SentenceView:
    """Independent view for sentence-breaks consumers.

    ``unsupported_lines`` uses 1-based physical source line numbers,
    never zero-based ``splitlines()`` indices.

    A line in ``unsupported_lines`` means "unknown, do not break here" —
    it also covers lines where inline alignment truncated, so an empty
    ``protected`` never means "nothing needs protection".
    """

    protected: tuple[SourceRange, ...]
    unsupported_lines: frozenset[int]


@dataclass(frozen=True)
class ConsumerViews:
    """Bundle of independent typed views produced by classification."""

    inline: InlineView
    strong: StrongView
    sentence: SentenceView
