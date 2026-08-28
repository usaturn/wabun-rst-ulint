"""Shared bounded ``inline-spacing`` fixer for the Issue #15 release gate.

Test-only. Wraps :func:`inline_spacing.fix_document` with the bounded-cost and
parse-safety assertions the gate requires, so the generated catalog and the
focused convergence fixture check exactly the same contract.
"""

from __future__ import annotations

from collections import Counter

from tests.helpers.rst_fingerprint import SemanticFingerprint, fingerprint, messages_delta_safe
from wabun_rst_ulint.checkers import inline_spacing
from wabun_rst_ulint.checkers._inline_classifier import last_classification_stats

OPAQUE_ROLES = ("term",)


def assert_parse_safe(before: SemanticFingerprint, after: SemanticFingerprint) -> None:
    """Assert a repair degraded neither docutils structure nor inline nodes."""
    # Structure: the authored block sequence must survive verbatim. A fixer that
    # inserted blank lines instead of ASCII spaces would split one paragraph into
    # three and fail here. system_message subtrees are excluded on purpose: a
    # repair is allowed to remove a system_message (and the paragraph docutils
    # nests inside it), which is a message reduction, not structural damage.
    assert after.structural_blocks == before.structural_blocks
    # Inline nodes: exact equality is genuinely wrong here. Inserting a boundary
    # space promotes previously unparsed text into new inline nodes and can move a
    # space into a neighbour's rawsource, so both the node list and individual
    # rawsources legitimately change. The invariant that does hold is a kind
    # census: no inline kind present before may lose an occurrence. ``problematic``
    # is excluded because resolving it is the point of the repair, and because a
    # newly parsed reference to an undefined target legitimately introduces one.
    before_kinds = Counter(node.kind for node in before.inlines if node.kind != "problematic")
    after_kinds = Counter(node.kind for node in after.inlines)
    assert before_kinds - after_kinds == Counter()
    # Messages: one-directional by design. Reductions are deliberately permitted
    # because removing docutils warnings is the purpose of a boundary repair; only
    # a new or duplicated message is a degradation.
    assert messages_delta_safe(before.messages, after.messages)


def bounded_fixer(monkeypatch):
    """Return a ``fix(source)`` that gates cost and parse safety on every call."""
    parse_calls = 0
    real_parse = inline_spacing.parse_document

    def counted_parse(source: str):
        nonlocal parse_calls
        parse_calls += 1
        return real_parse(source)

    monkeypatch.setattr(inline_spacing, "parse_document", counted_parse)

    def fix(source: str):
        before_fingerprint = fingerprint(source, opaque_roles=OPAQUE_ROLES)
        before_calls = parse_calls
        result = inline_spacing.fix_document(source)
        assert parse_calls - before_calls <= 2
        stats = last_classification_stats()
        assert stats.parse_count == 1
        assert stats.scan_chars <= 64 * max(1, len(source))
        if not result.transaction_failure:
            after_fingerprint = fingerprint(result.text, opaque_roles=OPAQUE_ROLES)
            assert_parse_safe(before_fingerprint, after_fingerprint)
        return result

    return fix
