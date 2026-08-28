"""Frozen typed model contract (Issue #10 S2)."""

from __future__ import annotations

import dataclasses
from typing import get_type_hints

import pytest

from wabun_rst_ulint.checkers._inline_model import (
    ConsumerViews,
    EditDecision,
    InlineSpan,
    InlineView,
    RepairCandidate,
    SentenceView,
    SourceRange,
    StrongOwner,
    StrongView,
)


class TestFrozenModel:
    def test_all_types_are_frozen_dataclasses(self) -> None:
        for cls in (
            SourceRange,
            InlineSpan,
            RepairCandidate,
            StrongOwner,
            EditDecision,
            InlineView,
            StrongView,
            SentenceView,
            ConsumerViews,
        ):
            assert dataclasses.is_dataclass(cls)
            assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_source_range_fields(self) -> None:
        r = SourceRange(start=0, end=4, line=1, column=1)
        assert r.start == 0 and r.end == 4 and r.line == 1 and r.column == 1
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.start = 1  # type: ignore[misc]

    def test_no_shared_active_protected_boolean_fields(self) -> None:
        """S2 path must not reintroduce PR #3 shared boolean ownership."""
        for cls in (
            SourceRange,
            InlineSpan,
            RepairCandidate,
            StrongOwner,
            EditDecision,
            InlineView,
            StrongView,
            SentenceView,
            ConsumerViews,
        ):
            names = {f.name for f in dataclasses.fields(cls)}
            assert "active" not in names, cls
            assert "protected" not in names or cls is SentenceView
            # SentenceView.protected is a tuple of SourceRange, not a bool
            if cls is SentenceView:
                hints = get_type_hints(SentenceView)
                assert "bool" not in str(hints["protected"])
                assert names == {"protected", "unsupported_lines"}

    def test_edit_decision_status_literal(self) -> None:
        cand = RepairCandidate(
            source_range=SourceRange(0, 2, 1, 1),
            form="literal",
            expected_rawsource=" ``x`` ",
        )
        for status in ("accepted", "rejected", "unsupported"):
            d = EditDecision(candidate=cand, status=status, reason="test")  # type: ignore[arg-type]
            assert d.status == status

    def test_typed_view_differences(self) -> None:
        sr = SourceRange(0, 5, 1, 1)
        cand = RepairCandidate(source_range=sr, form="literal", expected_rawsource=" ``a`` ")
        decision = EditDecision(candidate=cand, status="accepted", reason="boundary-repair")
        owner = StrongOwner(
            source_range=sr,
            interior_range=SourceRange(2, 3, 1, 3),
            recognized_by_docutils=False,
        )
        inline = InlineView(decisions=(decision,))
        strong = StrongView(owners=(owner,))
        sentence = SentenceView(protected=(sr,), unsupported_lines=frozenset({2}))
        views = ConsumerViews(inline=inline, strong=strong, sentence=sentence)

        assert views.inline.decisions[0].status == "accepted"
        assert views.strong.owners[0].recognized_by_docutils is False
        assert 2 in views.sentence.unsupported_lines
        # Independence: fields differ by type/purpose
        assert hasattr(views.inline, "decisions") and not hasattr(views.inline, "owners")
        assert hasattr(views.strong, "owners") and not hasattr(views.strong, "decisions")
        assert hasattr(views.sentence, "protected") and not hasattr(views.sentence, "decisions")

    def test_inline_span_shape(self) -> None:
        span = InlineSpan(
            source_range=SourceRange(1, 8, 1, 2),
            kind="opaque_role",
            rawsource=":term:`X`",
            visible_text="X",
        )
        assert span.kind == "opaque_role"
        assert span.rawsource.startswith(":term:")
