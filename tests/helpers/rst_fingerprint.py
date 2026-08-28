"""Test-only docutils semantic fingerprint and oracle probes.

Production code must not import this module. Helpers parse RST with a
non-executing, non-inserting docutils configuration suitable for
differential contracts on the locked 0.22.x line.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from typing import Any

from docutils import nodes
from docutils.core import publish_doctree
from docutils.parsers.rst import roles

# Source/line wrapper at the start of system-message bodies, e.g.
# "<string>:1: (WARNING/2) ..." — semantic body is retained after strip.
_SOURCE_LINE_PREFIX = re.compile(r"^(?:<[^>\n]+>|[A-Za-z0-9_./\\-]+):\d+(?::\d+)?:\s*")
_LEVEL_TYPE_WRAPPER = re.compile(r"^\((?:DEBUG|INFO|WARNING|ERROR|SEVERE)/\d+\)\s*")

# Inline node types we record for semantic fingerprints.
_INLINE_TAGS = frozenset(
    {
        "literal",
        "emphasis",
        "strong",
        "reference",
        "target",
        "footnote_reference",
        "citation_reference",
        "substitution_reference",
        "title_reference",
        "interpreted",
        "inline",
        "problematic",
        "image",
        "math",
        "raw",
    }
)

# Structural / block-ish tags recorded in order (excluding text/document).
_BLOCK_TAGS = frozenset(
    {
        "paragraph",
        "section",
        "title",
        "literal_block",
        "block_quote",
        "bullet_list",
        "enumerated_list",
        "list_item",
        "definition_list",
        "definition_list_item",
        "term",
        "definition",
        "field_list",
        "field",
        "field_name",
        "field_body",
        "option_list",
        "option_list_item",
        "table",
        "note",
        "warning",
        "tip",
        "important",
        "caution",
        "danger",
        "error",
        "hint",
        "admonition",
        "sidebar",
        "topic",
        "line_block",
        "line",
        "comment",
        "transition",
        "doctest_block",
        "system_message",
    }
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "file_insertion_enabled": False,
    "raw_enabled": False,
    "halt_level": 6,  # never raise SystemMessage
    "report_level": 5,  # suppress stream chatter; messages still on tree
    "warning_stream": StringIO(),
    "traceback": False,
}


@dataclass(frozen=True)
class InlineNodeFingerprint:
    """One inline node in document order."""

    kind: str
    rawsource: str
    visible_text: str


@dataclass(frozen=True)
class SemanticFingerprint:
    """Stable semantic view of a parsed RST document."""

    block_kinds: tuple[str, ...]
    inlines: tuple[InlineNodeFingerprint, ...]
    document_text: str
    messages: Counter[tuple[int, str, str]]
    # block_kinds minus every system_message subtree: the authored document
    # structure, comparable across a repair that removes a system_message
    # (and the paragraph docutils nests inside it).
    structural_blocks: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlignedInline:
    """Order-preserving alignment of an inline fingerprint to source offsets."""

    kind: str
    rawsource: str
    visible_text: str
    start: int
    end: int


def normalize_message_body(body: str) -> str:
    """Strip source/line wrappers; keep semantic message text."""
    text = body.strip()
    text = _SOURCE_LINE_PREFIX.sub("", text, count=1)
    text = _LEVEL_TYPE_WRAPPER.sub("", text, count=1)
    # Drop unstable generated id/backref listings that docutils appends.
    text = re.sub(r"\s*See \"backrefs\" attribute for IDs\.\s*", " ", text)
    text = re.sub(r"\bid[s]?\s*[:=]\s*[\"']?[a-z0-9-]+[\"']?", "", text, flags=re.I)
    return " ".join(text.split())


def message_key(node: nodes.system_message) -> tuple[int, str, str]:
    """Stable multiset key for a system_message node."""
    level = int(node["level"])
    msg_type = str(node["type"])
    body = normalize_message_body(node.astext())
    return (level, msg_type, body)


def messages_counter(document: nodes.document) -> Counter[tuple[int, str, str]]:
    return Counter(message_key(n) for n in document.findall(nodes.system_message))


def messages_delta_safe(
    before: Counter[tuple[int, str, str]],
    after: Counter[tuple[int, str, str]],
) -> bool:
    """True iff after has no positive count above before (duplicate increase fails)."""
    return after - before == Counter()


def _inline_kind(node: nodes.Node) -> str:
    if isinstance(node, nodes.inline):
        classes = list(node.get("classes") or [])
        if "opaque-role" in classes or any(c == "opaque_role" for c in classes):
            return "opaque_role"
        # Roles registered via scoped_opaque_roles mark classes=['opaque-role', name]
        if classes and classes[0] == "opaque-role":
            return "opaque_role"
    return node.tagname


def _structural_block_kinds(document: nodes.document) -> tuple[str, ...]:
    """Block kinds in document order, skipping system_message subtrees."""
    kinds: list[str] = []

    def walk(parent: nodes.Node) -> None:
        for child in parent.children:
            if isinstance(child, nodes.system_message):
                continue
            if child.tagname in _BLOCK_TAGS:
                kinds.append(child.tagname)
            walk(child)

    walk(document)
    return tuple(kinds)


def _normalize_ids_backrefs(document: nodes.document) -> None:
    """Clear generated ids/backrefs that are unstable across parses."""
    for node in document.findall():
        if "ids" in node:
            node["ids"] = []
        if "backrefs" in node:
            node["backrefs"] = []
        if "names" in node and not isinstance(node, nodes.target):
            # Keep explicit target names; drop auto names on other nodes.
            pass


@contextmanager
def scoped_opaque_roles(*role_names: str) -> Iterator[None]:
    """Register role names as generic opaque inlines; restore afterward."""
    previous: dict[str, Any] = {}
    for name in role_names:
        previous[name] = roles._roles.get(name)  # type: ignore[attr-defined]

        def _make_role(role_name: str):
            def _role(
                role: str,
                rawtext: str,
                text: str,
                lineno: int,
                inliner: Any,
                options: dict[str, Any] | None = None,
                content: list[str] | None = None,
            ) -> tuple[list[nodes.Node], list[nodes.system_message]]:
                del role, lineno, inliner, options, content
                node = nodes.inline(rawtext, nodes.unescape(text))
                node["classes"] = ["opaque-role", role_name]
                return [node], []

            return _role

        roles.register_local_role(name, _make_role(name))
    try:
        yield
    finally:
        for name, prior in previous.items():
            if prior is None:
                roles._roles.pop(name, None)  # type: ignore[attr-defined]
            else:
                roles._roles[name] = prior  # type: ignore[attr-defined]


def parse_rst(
    source: str,
    *,
    opaque_roles: Sequence[str] = (),
    settings_overrides: dict[str, Any] | None = None,
) -> nodes.document:
    """Publish a doctree with safe, non-executing settings."""
    settings = dict(DEFAULT_SETTINGS)
    if settings_overrides:
        settings.update(settings_overrides)
    # Fresh warning stream per parse
    settings["warning_stream"] = StringIO()
    with scoped_opaque_roles(*opaque_roles):
        document = publish_doctree(source=source, settings_overrides=settings)
    _normalize_ids_backrefs(document)
    return document


def fingerprint(
    source: str,
    *,
    opaque_roles: Sequence[str] = (),
    settings_overrides: dict[str, Any] | None = None,
) -> SemanticFingerprint:
    """Build a semantic fingerprint for *source*."""
    document = parse_rst(
        source,
        opaque_roles=opaque_roles,
        settings_overrides=settings_overrides,
    )
    block_kinds: list[str] = []
    inlines: list[InlineNodeFingerprint] = []
    for node in document.findall():
        if isinstance(node, nodes.Text) or node.tagname == "document":
            continue
        tag = node.tagname
        if tag in _BLOCK_TAGS:
            block_kinds.append(tag)
        if tag in _INLINE_TAGS or (isinstance(node, nodes.inline) and tag == "inline"):
            kind = _inline_kind(node)
            raw = node.rawsource if node.rawsource is not None else ""
            inlines.append(
                InlineNodeFingerprint(
                    kind=kind,
                    rawsource=raw,
                    visible_text=node.astext(),
                )
            )
    return SemanticFingerprint(
        block_kinds=tuple(block_kinds),
        inlines=tuple(inlines),
        document_text=document.astext(),
        messages=messages_counter(document),
        structural_blocks=_structural_block_kinds(document),
    )


def align_inlines_to_source(
    source: str,
    inlines: Sequence[InlineNodeFingerprint],
) -> list[AlignedInline]:
    """Order-preserving search of each inline rawsource within *source*.

    Returns only successfully aligned entries. Callers treat a full match
    (len(result) == len(inlines) with monotonic starts) as 100% alignment.
    """
    aligned: list[AlignedInline] = []
    cursor = 0
    for item in inlines:
        raw = item.rawsource
        if not raw:
            return aligned  # cannot align empty rawsource deterministically
        idx = source.find(raw, cursor)
        if idx < 0:
            # Fallback: try from start (non-order-preserving) — still record miss
            # by aborting order-preserving alignment for remaining items.
            return aligned
        end = idx + len(raw)
        aligned.append(
            AlignedInline(
                kind=item.kind,
                rawsource=raw,
                visible_text=item.visible_text,
                start=idx,
                end=end,
            )
        )
        cursor = end
    return aligned


def must_fix_source_alignment_report(
    cases: Sequence[Any],
    *,
    opaque_roles: Sequence[str] = ("term", "ref", "name", "doc", "class", "func"),
) -> dict[str, Any]:
    """Honest order-preserving AST/source alignment of must_fix *sources*.

    Issue #8 / #9 Go/No-Go metric (no silent redefinition):

    1. ``fingerprint(case.source)`` only — never ``case.expected`` for the node list.
    2. ``align_inlines_to_source(case.source, inlines)`` for offsets in source.
    3. Empty inline lists are **failures** (boundary-deficient inputs that
       docutils does not promote to inline nodes cannot be AST-aligned).

    ``s2_blocked`` (``rate < 1.0``) is the field name PR #18 recorded its
    evidence under, kept for provenance. It is **no longer a live block on
    S2** — read it as "pure-docutils alignment is incomplete", not as
    "S2 must stop".

    Gate history, so the name does not mislead:

    - Issue #8 / #9 originally gated S2 on ``rate == 1.0``.
    - S1 measured 30/55 (~54.5%). This is *structural*, not a defect: 25 of
      the 55 must_fix sources are boundary-deficient, so docutils 0.22.4
      never promotes them to inline nodes at all. No parser-only metric can
      reach 100% on inputs whose whole point is that the parser misreads
      them.
    - PR #20 re-deliberated the architecture (Issue #8 "100% 未満の場合 …
      architecture を再審議する") and moved the gate to **supported
      classification** on the narrow repair grammar + ``StrongOwner``. That
      superseding gate is ``test_must_fix_accepted_rate_100`` in
      ``tests/test_inline_classifier.py`` and holds at 100%.
    - Corpus cases were **not** downgraded; the failures below stay
      ``must_fix=True``.

    So this report is frozen S1 regression evidence. A change in ``ok`` /
    ``total`` means docutils' inline promotion changed and the repair
    grammar's assumptions need re-checking — it does not mean S2 regressed.
    """
    must = [c for c in cases if getattr(c, "must_fix", False)]
    ok_ids: list[str] = []
    fail_ids: list[str] = []
    empty_inline_ids: list[str] = []
    details: list[dict[str, Any]] = []
    for case in must:
        source = case.source
        # Honest metric: parse the must_fix *source* only.
        result = fingerprint(source, opaque_roles=opaque_roles)
        if not result.inlines:
            fail_ids.append(case.id)
            empty_inline_ids.append(case.id)
            details.append(
                {
                    "id": case.id,
                    "ok": False,
                    "reason": "empty_inlines",
                    "aligned": 0,
                    "total": 0,
                    "node_source": "source",
                }
            )
            continue
        aligned = align_inlines_to_source(source, result.inlines)
        success = len(aligned) == len(result.inlines)
        if success:
            success = all(0 <= a.start < a.end <= len(source) for a in aligned)
            success = success and all(source[a.start : a.end] == a.rawsource for a in aligned)
        if success:
            ok_ids.append(case.id)
        else:
            fail_ids.append(case.id)
        details.append(
            {
                "id": case.id,
                "ok": success,
                "reason": None if success else "partial_or_miss",
                "aligned": len(aligned),
                "total": len(result.inlines),
                "rawsources": [i.rawsource for i in result.inlines],
                "node_source": "source",
            }
        )
    total = len(must)
    rate = 1.0 if total == 0 else len(ok_ids) / total
    # PR #18 evidence field name; superseded as a gate by PR #20. See docstring.
    s2_blocked = rate < 1.0
    return {
        "total": total,
        "ok": len(ok_ids),
        "failed": len(fail_ids),
        "empty_inlines": len(empty_inline_ids),
        "rate": rate,
        "s2_blocked": s2_blocked,
        "ok_ids": ok_ids,
        "fail_ids": fail_ids,
        "empty_inline_ids": empty_inline_ids,
        "details": details,
        "metric": "fingerprint(source)+align(source); empty_inlines=fail",
    }


def must_fix_alignment_rate(
    cases: Sequence[Any],
    *,
    opaque_roles: Sequence[str] = ("term", "ref", "name", "doc", "class", "func"),
) -> float:
    """Fraction of must_fix cases with full order-preserving alignment on source."""
    return float(must_fix_source_alignment_report(cases, opaque_roles=opaque_roles)["rate"])


def probe_opaque_role_kind(source: str, role_name: str = "ref") -> str | None:
    """Parse *source* with *role_name* registered opaque; return first inline kind."""
    fp = fingerprint(source, opaque_roles=(role_name,))
    for item in fp.inlines:
        if item.kind == "opaque_role":
            return item.kind
    return None
