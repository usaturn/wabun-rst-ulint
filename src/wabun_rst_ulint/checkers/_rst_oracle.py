"""Secure docutils syntax oracle adapter (Issue #10).

Isolates parser I/O and role-registry mutation. Production classification
imports only this adapter for docutils interaction.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from typing import Any

import docutils
from docutils import nodes
from docutils.core import publish_doctree
from docutils.parsers.rst import roles
from docutils.utils import SystemMessage as DocutilsSystemMessage

from wabun_rst_ulint.checkers._inline_model import InlineSpan, SourceRange

# Supported runtime minor line (Issue #8 / #10).
_DOCUTILS_MAJOR_MINOR_RE = re.compile(r"^(\d+)\.(\d+)")

# Syntactically valid role name token (prefix form): :name:
_ROLE_NAME_RE = re.compile(r":([A-Za-z][A-Za-z0-9_.+:-]*):`")

# Postfix role form also exposes a name; still a role name for opaque registration.
_POSTFIX_ROLE_NAME_RE = re.compile(r"`[^`\n]+`:([A-Za-z][A-Za-z0-9_.+:-]*):")

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

# Known docutils admonition / body-checkable directive names (non-Sphinx).
CHECKABLE_DIRECTIVES = frozenset(
    {
        "note",
        "warning",
        "tip",
        "important",
        "caution",
        "danger",
        "error",
        "hint",
        "admonition",
        "seealso",
        "attention",
    }
)

# Bodies that are opaque / non-editable without Sphinx or execution.
OPAQUE_DIRECTIVES = frozenset(
    {
        "code-block",
        "code",
        "sourcecode",
        "literalinclude",
        "raw",
        "parsed-literal",
        "math",
        "highlight",
        "include",
        "csv-table",
        "mermaid",
    }
)

_DIRECTIVE_LINE_RE = re.compile(r"^\.\.\s+(\S+)::")


class OracleVersionError(RuntimeError):
    """Raised when the imported docutils minor is outside the supported line."""


@dataclass
class OracleCounters:
    """Mutable instrumentation for one classification cycle."""

    parse_count: int = 0
    scan_chars: int = 0


@dataclass(frozen=True)
class OracleInline:
    """Inline node extracted from the doctree before physical mapping."""

    kind: str
    rawsource: str
    visible_text: str
    line: int | None  # docutils 1-based line when available


@dataclass(frozen=True)
class AlignedInline:
    """Order-preserving alignment of an oracle inline to absolute offsets."""

    kind: str
    rawsource: str
    visible_text: str
    start: int
    end: int
    line: int
    column: int


@dataclass(frozen=True)
class OracleDocument:
    """Result of one secure oracle parse."""

    document: nodes.document
    inlines: tuple[OracleInline, ...]
    opaque_roles_registered: tuple[str, ...]
    warning_stream: StringIO
    counters: OracleCounters


def require_supported_docutils() -> str:
    """Return the imported version string or raise OracleVersionError."""
    version = docutils.__version__
    match = _DOCUTILS_MAJOR_MINOR_RE.match(version)
    if match is None:
        raise OracleVersionError(f"unparseable docutils version: {version!r}")
    major, minor = int(match.group(1)), int(match.group(2))
    if major != 0 or minor != 22:
        raise OracleVersionError(
            f"docutils {version} is outside the supported range >=0.22,<0.23; refusing to run the syntax oracle"
        )
    return version


_SECURE_SETTING_LOCK: dict[str, Any] = {
    "_disable_config": True,
    "file_insertion_enabled": False,
    "raw_enabled": False,
    "halt_level": 5,
    "traceback": True,
}


def default_settings() -> dict[str, Any]:
    """Fixed secure settings for the Issue #10 oracle contract."""
    return {
        "file_insertion_enabled": False,
        "raw_enabled": False,
        "report_level": 1,
        "halt_level": 5,
        "warning_stream": StringIO(),
        "input_encoding": "unicode",
        "traceback": True,
        "_disable_config": True,
    }


def _apply_secure_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Force contract keys after optional caller overrides."""
    settings.update(_SECURE_SETTING_LOCK)
    return settings


def discover_role_names(source: str, *, counters: OracleCounters | None = None) -> tuple[str, ...]:
    """Lexical pre-scan for syntactically valid role names (source order, unique).

    Names are lowercased to match ``roles.register_local_role`` storage keys.
    """
    if counters is not None:
        counters.scan_chars += len(source)
    names: list[str] = []
    seen: set[str] = set()
    for match in _ROLE_NAME_RE.finditer(source):
        key = match.group(1).lower()
        if key not in seen:
            seen.add(key)
            names.append(key)
    for match in _POSTFIX_ROLE_NAME_RE.finditer(source):
        key = match.group(1).lower()
        if key not in seen:
            seen.add(key)
            names.append(key)
    return tuple(names)


@contextmanager
def scoped_opaque_roles(*role_names: str) -> Iterator[None]:
    """Register role names as generic opaque inlines; restore afterward.

    Registry keys are always lowercased because
    ``roles.register_local_role`` stores under ``name.lower()``.
    """
    previous: dict[str, Any] = {}
    seen: set[str] = set()
    for name in role_names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        previous[key] = roles._roles.get(key)  # type: ignore[attr-defined]

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

        roles.register_local_role(key, _make_role(key))
    try:
        yield
    finally:
        for key, prior in previous.items():
            if prior is None:
                roles._roles.pop(key, None)  # type: ignore[attr-defined]
            else:
                roles._roles[key] = prior  # type: ignore[attr-defined]


def _inline_kind(node: nodes.Node) -> str:
    if isinstance(node, nodes.inline):
        classes = list(node.get("classes") or [])
        if "opaque-role" in classes or "opaque_role" in classes:
            return "opaque_role"
        if classes and classes[0] == "opaque-role":
            return "opaque_role"
    return node.tagname


def _has_literal_block_ancestor(node: nodes.Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.tagname == "literal_block":
            return True
        parent = parent.parent
    return False


def _extract_inlines(document: nodes.document) -> tuple[OracleInline, ...]:
    out: list[OracleInline] = []
    for node in document.findall():
        if isinstance(node, nodes.Text) or node.tagname == "document":
            continue
        if _has_literal_block_ancestor(node):
            continue
        tag = node.tagname
        if tag in _INLINE_TAGS or (isinstance(node, nodes.inline) and tag == "inline"):
            kind = _inline_kind(node)
            raw = node.rawsource if node.rawsource is not None else ""
            line = node.line if isinstance(getattr(node, "line", None), int) else None
            out.append(
                OracleInline(
                    kind=kind,
                    rawsource=raw,
                    visible_text=node.astext(),
                    line=line,
                )
            )
    return tuple(out)


def parse_document(
    source: str,
    *,
    opaque_roles: Sequence[str] | None = None,
    counters: OracleCounters | None = None,
    settings_overrides: dict[str, Any] | None = None,
) -> OracleDocument:
    """One secure full-document parse. Increments ``counters.parse_count``."""
    require_supported_docutils()
    ctr = counters if counters is not None else OracleCounters()
    roles_to_register = tuple(opaque_roles) if opaque_roles is not None else discover_role_names(source, counters=ctr)
    settings = default_settings()
    if settings_overrides:
        settings.update(settings_overrides)
    _apply_secure_settings(settings)
    # Always use a fresh stream so callers can inspect capture.
    warning_stream = StringIO()
    settings["warning_stream"] = warning_stream
    with scoped_opaque_roles(*roles_to_register):
        try:
            document = publish_doctree(source=source, settings_overrides=settings)
        except DocutilsSystemMessage:
            # halt_level=5 should avoid this; re-raise as opaque failure signal
            raise
        except SystemExit as exc:
            # Defense in depth: library path must never terminate the host.
            raise RuntimeError("docutils attempted to exit the process during parse_document") from exc
    ctr.parse_count += 1
    return OracleDocument(
        document=document,
        inlines=_extract_inlines(document),
        opaque_roles_registered=roles_to_register,
        warning_stream=warning_stream,
        counters=ctr,
    )


def newline_offsets(source: str) -> list[int]:
    """Return absolute indices of every ``\\n`` in *source* (single scan)."""
    return [i for i, ch in enumerate(source) if ch == "\n"]


def offset_to_line_column(
    source: str,
    offset: int,
    *,
    newlines: Sequence[int] | None = None,
) -> tuple[int, int]:
    """Map absolute 0-based offset to 1-based (line, column)."""
    if offset < 0:
        offset = 0
    if offset > len(source):
        offset = len(source)
    if newlines is None:
        line = source.count("\n", 0, offset) + 1
        last_nl = source.rfind("\n", 0, offset)
    else:
        # newlines[i] = index of i-th '\n'; count of newlines strictly before offset
        line = bisect.bisect_left(newlines, offset) + 1
        last_nl = newlines[line - 2] if line >= 2 else -1
    column = offset + 1 if last_nl < 0 else offset - last_nl
    return line, column


def make_source_range(
    source: str,
    start: int,
    end: int,
    *,
    newlines: Sequence[int] | None = None,
) -> SourceRange:
    """Build a SourceRange from absolute character offsets."""
    line, column = offset_to_line_column(source, start, newlines=newlines)
    return SourceRange(start=start, end=end, line=line, column=column)


def align_inlines_to_source(
    source: str,
    inlines: Sequence[OracleInline],
    *,
    counters: OracleCounters | None = None,
    newlines: Sequence[int] | None = None,
) -> list[AlignedInline]:
    """Order-preserving 1:1 alignment of inline rawsource within *source*.

    Thin wrapper over :func:`align_inlines_with_status` that drops the
    truncation line. Consumers that must fail closed on partial alignment
    should call :func:`align_inlines_with_status` instead.
    """
    aligned, _ = align_inlines_with_status(source, inlines, counters=counters, newlines=newlines)
    return aligned


def align_inlines_with_status(
    source: str,
    inlines: Sequence[OracleInline],
    *,
    counters: OracleCounters | None = None,
    newlines: Sequence[int] | None = None,
) -> tuple[list[AlignedInline], int | None]:
    """Align inlines and report where alignment stopped.

    Returns ``(aligned, truncated_from_line)``. ``truncated_from_line`` is
    ``None`` when every inline aligned; otherwise it is the 1-based physical
    line of the first character that was never covered, so consumers can treat
    that line onward as unknown instead of assuming "nothing to protect".

    Repeated identical rawsource is resolved by monotonic cursor advancement.
    Stops early when a rawsource cannot be found at/after the cursor (no
    arbitrary nearest/first-from-start fallback for remaining items).
    """
    if counters is not None:
        counters.scan_chars += len(source)
    if newlines is None:
        newlines = newline_offsets(source)
    aligned: list[AlignedInline] = []
    cursor = 0
    for item in inlines:
        raw = item.rawsource
        if not raw:
            return aligned, offset_to_line_column(source, cursor, newlines=newlines)[0]
        idx = source.find(raw, cursor)
        if idx < 0:
            return aligned, offset_to_line_column(source, cursor, newlines=newlines)[0]
        end = idx + len(raw)
        line, column = offset_to_line_column(source, idx, newlines=newlines)
        aligned.append(
            AlignedInline(
                kind=item.kind,
                rawsource=raw,
                visible_text=item.visible_text,
                start=idx,
                end=end,
                line=line,
                column=column,
            )
        )
        cursor = end
    return aligned, None


def aligned_to_spans(
    source: str,
    aligned: Sequence[AlignedInline],
    *,
    newlines: Sequence[int] | None = None,
) -> tuple[InlineSpan, ...]:
    """Convert aligned inlines to frozen InlineSpan records."""
    spans: list[InlineSpan] = []
    for item in aligned:
        spans.append(
            InlineSpan(
                source_range=make_source_range(source, item.start, item.end, newlines=newlines),
                kind=item.kind,
                rawsource=item.rawsource,
                visible_text=item.visible_text,
            )
        )
    return tuple(spans)


def opaque_body_ranges(source: str, *, counters: OracleCounters | None = None) -> list[tuple[int, int]]:
    """Absolute character ranges of opaque directive / literal-block bodies.

    Oracle authority: unknown/Sphinx-like and listed opaque directives, plus
    ``::``-introduced literal blocks. Checkable admonitions are excluded.
    Footnote / citation / substitution definition bodies are checkable.
    """
    if counters is not None:
        counters.scan_chars += len(source)
    ranges: list[tuple[int, int]] = []
    lines = source.splitlines(keepends=True)
    offset = 0
    skip_indent: int | None = None
    for raw_line in lines:
        stripped = raw_line.rstrip("\n").rstrip("\r")
        indent = len(stripped) - len(stripped.lstrip())
        line_start = offset
        line_end = offset + len(raw_line)

        if skip_indent is not None:
            if stripped == "":
                ranges.append((line_start, line_end))
                offset = line_end
                continue
            if indent > skip_indent:
                ranges.append((line_start, line_end))
                offset = line_end
                continue
            skip_indent = None

        lstripped = stripped.lstrip()
        is_directive = False
        if lstripped.startswith(".. ") or lstripped == "..":
            match = _DIRECTIVE_LINE_RE.match(lstripped)
            if match:
                name = match.group(1).lower()
                # Footnotes/citations: .. [1] / .. [CIT] — not directives with ::
                # Substitution: .. |m| replace:: — directive name is replace
                if name == "replace" or name in CHECKABLE_DIRECTIVES:
                    is_opaque = False
                elif name in OPAQUE_DIRECTIVES or ":" in match.group(1):
                    is_opaque = True
                else:
                    # Unknown directive name → opaque body (reachability here
                    # already implies name not in CHECKABLE_DIRECTIVES)
                    is_opaque = True
                if is_opaque:
                    skip_indent = indent
                    # Directive line itself is structural; body lines follow
                    offset = line_end
                    continue
                is_directive = True
            else:
                # Comment or footnote/citation style
                # Footnote/citation definition: .. [1] / .. [CIT] — checkable,
                # whether the body starts on the same line or on the next
                # indented lines. Never route through the comment skip path.
                if re.match(r"^\.\.\s+\[[^\]]+\]", lstripped):
                    offset = line_end
                    continue
                # Substitution definition with body on following lines:
                # .. |m| replace:: — checkable; must not fall through to the
                # literal-block trigger below.
                if re.match(r"^\.\.\s+\|[^|]+\|\s+\S+::", lstripped):
                    offset = line_end
                    continue
                # Plain comment: indented body lines are opaque
                skip_indent = indent
                offset = line_end
                continue

        if not is_directive and stripped.endswith("::"):
            skip_indent = indent
            # trigger line remains checkable
        offset = line_end

    return _merge_ranges(ranges)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ranges = sorted(ranges)
    merged: list[list[int]] = [[ranges[0][0], ranges[0][1]]]
    for start, end in ranges[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def range_in_opaque(start: int, end: int, opaque: Sequence[tuple[int, int]]) -> bool:
    """True if [start, end) is fully inside an opaque body, or *start* lies inside one.

    Partial overlap that merely *touches* an opaque region from outside
    (start < o_start < end) is **not** treated as opaque. This matches S2's
    candidate filtering: only marks whose start is already inside a non-editable
    body are suppressed.
    """
    for o_start, o_end in opaque:
        if start >= o_start and end <= o_end:
            return True
        if o_start <= start < o_end:
            return True
    return False


def role_registry_has(name: str) -> bool:
    """Test helper: whether *name* is currently in the local role registry."""
    return name.lower() in roles._roles  # type: ignore[attr-defined]
