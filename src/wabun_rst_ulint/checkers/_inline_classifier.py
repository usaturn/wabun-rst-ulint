"""Narrow repair-grammar classifier producing independent consumer views.

Classify only — never apply edits or perform file I/O (Issue #10).
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from docutils.utils import punctuation_chars

from wabun_rst_ulint.checkers._inline_model import (
    ConsumerViews,
    EditDecision,
    InlineView,
    RepairCandidate,
    SentenceView,
    SourceRange,
    StrongOwner,
    StrongView,
)
from wabun_rst_ulint.checkers._rst_oracle import (
    OracleCounters,
    align_inlines_with_status,
    aligned_to_spans,
    make_source_range,
    newline_offsets,
    offset_to_line_column,
    opaque_body_ranges,
    parse_document,
    range_in_opaque,
)

# --- Lexical patterns for supported forms (narrow grammar) ---

LITERAL_RE = re.compile(r"``(?:[^`]|`(?!`))+``")
# Prefix role :name:`payload`
PREFIX_ROLE_RE = re.compile(r":([A-Za-z][A-Za-z0-9_.+:-]*):`([^`\n]+)`")
# Postfix role `payload`:name:
POSTFIX_ROLE_RE = re.compile(r"`([^`\n]+)`:([A-Za-z][A-Za-z0-9_.+:-]*):")
# Named / anonymous reference `phrase`_ / `phrase`__
NAMED_REF_RE = re.compile(r"`([^`\n]+)`(__?)(?![`_])")
# Internal target _`payload`
INTERNAL_TARGET_RE = re.compile(r"_`([^`\n]+)`")
# Simpler interp: bare `word` not part of other forms — applied after masks
SIMPLE_INTERP_RE = re.compile(r"(?<![`\\])`([^`\n]+)`(?!`)")
# Complete single-line ``...`` token for SentenceView protection only.
_SENTENCE_LITERAL_RE = re.compile(r"``(?:[^`\n]|`(?!`))+``")

# Complete single-line *...* token for SentenceView protection only.
# External start/end adjacency is intentionally not required: this view must
# protect a closed token even when docutils cannot recognize its boundaries.
_SENTENCE_EMPHASIS_RE = re.compile(r"(?<!\*)\*(?![\s*])(?:[^*\n]*?[^\s*\n])\*(?!\*)")

_ASTERISK_FOOTNOTE_RE = re.compile(r"^\s*\.\.\s+\[\*\](?:\s|$)")
_ASTERISK_START_BEFORE_RE = re.compile("[%s%s]" % (punctuation_chars.openers, punctuation_chars.delimiters))

# Outer strong **...** on a single physical line (non-greedy).
# Multi-line boundary-deficient strong is out of S2 scope (S3+ follow-up).
# The `*` lookarounds keep `***x***` out of the grammar: a non-greedy match
# there would own the asymmetric `***x**` and S4's outer space would split it.
STRONG_RE = re.compile(r"(?<!\*)\*\*(?!\s|\*)(.+?)(?<!\*)\*\*(?!\*)")
# Boundary null escape: backslash + ASCII space
NULL_ESCAPE_RE = re.compile(r"\\ ")
# Bare `:name` opener probe used by the null-escape pass (matched with pos=)
_ROLE_COLON_RE = re.compile(r":[A-Za-z]")

# Whitespace that normalizes to ASCII space at external boundaries
_BOUNDARY_WS = frozenset({"\t", "\u00a0", "\u3000"})

# Characters that may abut a token without needing a visible space (form-dependent).
# Literals: docutils end punctuation including CJK 。 may stay adjacent after.
_LITERAL_OK_AFTER = frozenset(
    {
        " ",
        ".",
        ",",
        ";",
        ":",
        "!",
        "?",
        ")",
        "]",
        "}",
        ">",
        "-",
        "/",
        "'",
        '"',
        "\\",
        # docutils punctuation_chars.closers (CJK); pairs with the openers in
        # _LITERAL_OK_BEFORE. Full-width 、。！？：；・… beyond this set are
        # tracked with the role-side decision in Issue #22.
        "。",
        "、",
        "」",
        "』",
        "）",
        "】",
        "〉",
        "》",
        "〕",
        "〗",
        "\n",
    }
)
_LITERAL_OK_BEFORE = frozenset(
    {
        " ",
        "(",
        "[",
        "{",
        "<",
        "-",
        "/",
        ":",
        "'",
        '"',
        "\\",
        "\n",
        # docutils punctuation_chars.openers (CJK); 1:1 with the CJK closers in
        # _LITERAL_OK_AFTER
        "（",
        "「",
        "『",
        "【",
        "〈",
        "《",
        "〔",
        "〖",
    }
)

# Role/ref/target/interp: visible-space style — only space or backslash is ok.
_VISIBLE_OK = frozenset({" ", "\\"})


@dataclass(frozen=True)
class _RawCandidate:
    start: int
    end: int
    form: str
    raw: str
    # edit span may expand for null-escape / boundary ws normalization
    edit_start: int
    edit_end: int
    expected_rawsource: str
    status: str = "accepted"
    reason: str = "boundary-repair"


@dataclass
class ClassificationStats:
    """Exposed for performance tests."""

    parse_count: int = 0
    scan_chars: int = 0


_LAST_STATS = ClassificationStats()


def last_classification_stats() -> ClassificationStats:
    """Return counters from the most recent ``classify_document`` call."""
    return ClassificationStats(
        parse_count=_LAST_STATS.parse_count,
        scan_chars=_LAST_STATS.scan_chars,
    )


def _line_bounds(source: str) -> list[tuple[int, int, int]]:
    """List of (line_no_1based, start_offset, end_offset_exclusive) per physical line."""
    bounds: list[tuple[int, int, int]] = []
    offset = 0
    line_no = 1
    while offset <= len(source):
        nl = source.find("\n", offset)
        if nl < 0:
            bounds.append((line_no, offset, len(source)))
            break
        bounds.append((line_no, offset, nl + 1))
        offset = nl + 1
        line_no += 1
        if offset == len(source):
            break
    return bounds


# Simple/grid table layout lines — boundary inserts would shift fixed columns.
_SIMPLE_TABLE_BORDER_RE = re.compile(r"^[ \t]*[-=]+(?:[ \t]+[-=]+)+[ \t]*$")
_GRID_TABLE_BORDER_RE = re.compile(r"^[ \t]*\+[-=+]+\+[ \t]*$")
_GRID_TABLE_ROW_RE = re.compile(r"^[ \t]*\|.*\|[ \t]*$")


def _table_layout_line_starts(source: str) -> frozenset[int]:
    """Start offsets of physical lines that participate in simple/grid tables.

    A line is included when it is a border, a grid row between borders, or a
    simple-table body line sandwiched by simple-table border lines in the
    same block. A single blank line between borders is part of the table
    (multi-line rows); two consecutive blank lines end the block.
    This is intentionally conservative (safe over-suppression).
    csv-table / list-table stay on the existing opaque path and are not handled
    here.
    """
    bounds = _line_bounds(source)
    lines = [source[s:e] for _, s, e in bounds]
    starts = [s for _, s, e in bounds]
    n = len(lines)
    marked = [False] * n

    # Grid: border lines and |...| rows in a contiguous run that includes a border
    i = 0
    while i < n:
        if _GRID_TABLE_BORDER_RE.match(lines[i]) or _GRID_TABLE_ROW_RE.match(lines[i]):
            j = i
            while j < n and (_GRID_TABLE_BORDER_RE.match(lines[j]) or _GRID_TABLE_ROW_RE.match(lines[j])):
                j += 1
            if any(_GRID_TABLE_BORDER_RE.match(lines[k]) for k in range(i, j)):
                for k in range(i, j):
                    marked[k] = True
            i = j
        else:
            i += 1

    # Simple: border lines and the lines between consecutive borders
    border_idx = [idx for idx, ln in enumerate(lines) if _SIMPLE_TABLE_BORDER_RE.match(ln)]
    for a, b in zip(border_idx, border_idx[1:], strict=False):
        if b <= a:
            continue
        # A simple table may separate multi-line rows with a single blank line.
        # Two consecutive blank lines end the block, so only those disqualify.
        blank = [lines[k].strip() == "" for k in range(a, b + 1)]
        if any(blank[k] and blank[k + 1] for k in range(len(blank) - 1)):
            continue
        for k in range(a, b + 1):
            marked[k] = True

    return frozenset(starts[idx] for idx, flag in enumerate(marked) if flag)


def _containment_index(spans: list[tuple[int, int]]) -> tuple[list[int], list[int]]:
    """Sorted starts plus prefix-max ends for O(log n) containment queries.

    Pairs with :func:`_span_covers`. Built once per document so per-candidate
    checks stop rescanning the whole span list (O(S x L) -> O(S log L)).
    """
    ordered = sorted(spans)
    starts = [s for s, _ in ordered]
    max_ends: list[int] = []
    running = -1
    for _, e in ordered:
        running = max(running, e)
        max_ends.append(running)
    return starts, max_ends


def _span_covers(index: tuple[list[int], list[int]], start: int, end: int) -> bool:
    """True if the indexed spans contain one with ``s <= start`` and ``e >= end``."""
    starts, max_ends = index
    i = bisect.bisect_right(starts, start) - 1
    return i >= 0 and max_ends[i] >= end


def _occupied_mask(length: int, spans: list[tuple[int, int]]) -> bytearray:
    mask = bytearray(length)
    for start, end in spans:
        for i in range(max(0, start), min(length, end)):
            mask[i] = 1
    return mask


def _span_free(mask: bytearray, start: int, end: int) -> bool:
    return all(mask[i] == 0 for i in range(start, end))


def _mark(mask: bytearray, start: int, end: int) -> None:
    for i in range(start, end):
        mask[i] = 1


def _expected_token_with_boundaries(
    source: str,
    start: int,
    end: int,
    raw: str,
    *,
    form: str,
) -> tuple[int, int, str]:
    """Compute edit range and expected_rawsource for a token needing boundary work.

    Edit range covers optional leading/trailing boundary whitespace or null-escape
    plus the token itself. expected_rawsource is the normalized slice.
    """
    edit_start = start
    edit_end = end
    before_extra = ""
    after_extra = ""

    # Leading null-escape immediately before token: `\ `
    if _is_null_escape_before(source, start) and not _is_line_initial(source, start - 2):
        edit_start = start - 2
        before_extra = " "
    elif start >= 1 and source[start - 1] in _BOUNDARY_WS and not _is_line_initial(source, start - 1):
        edit_start = start - 1
        before_extra = " "
    elif _needs_before_space(source, start, form=form):
        before_extra = " "

    # Trailing boundary
    if end < len(source) and source[end] in _BOUNDARY_WS:
        # Trailing WS: if rest of line is only this WS (+ optional newline), drop it
        line_end = source.find("\n", end)
        if line_end < 0:
            line_end = len(source)
        line_rest = source[end:line_end]
        if line_rest and all(ch in _BOUNDARY_WS for ch in line_rest):
            edit_end = end + len(line_rest)
            after_extra = ""
        else:
            edit_end = end + 1
            after_extra = " "
    elif _is_null_escape_after(source, end):
        edit_end = end + 2
        after_extra = " "
    elif _needs_after_space(source, end, form=form):
        after_extra = " "

    # expected_rawsource always carries the boundary pieces; the edit range
    # computed above decides which source chars the replacement consumes.
    expected = f"{before_extra}{raw}{after_extra}"

    return edit_start, edit_end, expected


def _is_line_initial(source: str, pos: int) -> bool:
    """True when *pos* is the first character of a physical line."""
    return pos == 0 or source[pos - 1] == "\n"


def _needs_before_space(source: str, start: int, *, form: str) -> bool:
    if start <= 0:
        return False
    ch = source[start - 1]
    if ch == "\n":
        return False  # line start is a valid external boundary (mirror of after-side)
    if ch in _BOUNDARY_WS:
        # Boundary WS opening a physical line must stay untouched: normalizing
        # it to an ASCII space would indent the line and change block structure.
        if _is_line_initial(source, start - 1):
            return False
        return True  # normalize path handled separately, still a need
    if form in {"literal"}:
        if ch in _LITERAL_OK_BEFORE or ch.isspace():
            return ch != " " and ch.isspace()
        return True
    # visible-space forms (role/ref/target/interp)
    if ch in _VISIBLE_OK:
        return False
    return True


def _needs_after_space(source: str, end: int, *, form: str) -> bool:
    if end >= len(source):
        return False
    ch = source[end]
    if ch == "\n":
        return False
    if ch in _BOUNDARY_WS:
        return True
    if form in {"literal"}:
        if ch in _LITERAL_OK_AFTER:
            return False
        return True
    # visible-space forms
    if ch in _VISIBLE_OK:
        return False
    return True


def _token_needs_repair(source: str, start: int, end: int, *, form: str) -> bool:
    if _is_null_escape_before(source, start) and not _is_line_initial(source, start - 2):
        return True
    if _is_null_escape_after(source, end):
        return True
    if start > 0 and source[start - 1] in _BOUNDARY_WS and not _is_line_initial(source, start - 1):
        return True
    if end < len(source) and source[end] in _BOUNDARY_WS:
        return True
    if _needs_before_space(source, start, form=form):
        return True
    if _needs_after_space(source, end, form=form):
        return True
    return False


def _is_markup_escaped(source: str, start: int) -> bool:
    """True when an odd number of backslashes immediately precede *start*."""
    n = 0
    i = start - 1
    while i >= 0 and source[i] == "\\":
        n += 1
        i -= 1
    return n % 2 == 1


def _is_null_escape_before(source: str, start: int) -> bool:
    r"""True when the two chars before *start* form an unescaped `\ ` pair."""
    if start < 2 or source[start - 2 : start] != "\\ ":
        return False
    n = 0
    i = start - 2
    while i >= 0 and source[i] == "\\":
        n += 1
        i -= 1
    return n % 2 == 1


def _is_null_escape_after(source: str, end: int) -> bool:
    r"""True when the two chars at *end* form an unescaped `\ ` pair."""
    if end >= len(source) - 1 or source[end : end + 2] != "\\ ":
        return False
    n = 0
    i = end - 1
    while i >= 0 and source[i] == "\\":
        n += 1
        i -= 1
    return n % 2 == 0


def _is_comment_line_at(source: str, offset: int) -> bool:
    """True if *offset* lies on a reST comment line (not directive/footnote/sub)."""
    line_start = source.rfind("\n", 0, offset) + 1
    line_end = source.find("\n", line_start)
    if line_end < 0:
        line_end = len(source)
    line = source[line_start:line_end]
    lstripped = line.lstrip()
    if not lstripped.startswith(".."):
        return False
    if re.match(r"\.\.\s+\S+::", lstripped):
        return False
    if re.match(r"\.\.\s+\[[^\]]+\]", lstripped):
        return False
    if re.match(r"\.\.\s+\|[^|]+\|\s+\S+::", lstripped):
        return False
    return True


def _literal_destroys_strong_or_emphasis(source: str, start: int, end: int) -> bool:
    """True when ``...`` is tightly wrapped by * or ** (Issue #4 family).

    Independent literal boundary inserts would destroy outer strong/emphasis.
    """
    # **``payload``** or *``payload``*
    if start >= 2 and end + 2 <= len(source) and source[start - 2 : start] == "**" and source[end : end + 2] == "**":
        return True
    if start >= 1 and end + 1 <= len(source) and source[start - 1] == "*" and source[end] == "*":
        # single-asterisk emphasis wrap; not ** (already handled)
        if start < 2 or source[start - 2] != "*":
            if end + 1 >= len(source) or source[end + 1] != "*":
                return True
    return False


def is_shared_boundary_literal(source: str, start: int, end: int) -> bool:
    """True only for contiguous shared-boundary runs like `` `x``-v`` ``.

    Decision table (literal span [start:end)):

    - ``... `x``-v`` ...`` → True (Issue #5 equal-score control)
    - ``before `a` ``b``after`` → False (space separates tokens)
    - ``前 `x` 後``y``です`` → False (completed single-tick + later literal)
    - ``後``y``です`` / ``値は``foo``です`` → False (no preceding single-tick)

    Rule (frozen): the char immediately before the literal's first `` ` `` must be
    non-whitespace non-backtick payload; walking left from there stays on
    non-whitespace/non-backtick until a single-tick opener that is not the
    second half of ``. Stop on whitespace, newline, or backtick.
    """
    if start < 1 or end > len(source):
        return False
    if start + 1 >= len(source) or source[start : start + 2] != "``":
        return False
    prev = source[start - 1]
    if prev.isspace() or prev in "`\n":
        return False
    # Contiguous payload only — stop on whitespace / backtick / newline
    j = start - 1
    while j >= 0 and not source[j].isspace() and source[j] not in "`\n":
        j -= 1
    if j < 0 or source[j] != "`":
        return False
    if j + 1 >= start:
        return False
    # Opener must not be the second half of another ``
    if j > 0 and source[j - 1] == "`":
        return False
    return True


def _role_owned_payload_spans(source: str) -> frozenset[tuple[int, int]]:
    """Collect role payload backtick spans once (prefix + postfix)."""
    owned: set[tuple[int, int]] = set()
    for m in PREFIX_ROLE_RE.finditer(source):
        # :name:`payload` — payload backticks are the trailing `...`
        raw = m.group(0)
        tick = raw.find("`")
        if tick < 0:
            continue
        abs_start = m.start() + tick
        owned.add((abs_start, m.end()))
    for m in POSTFIX_ROLE_RE.finditer(source):
        payload = f"`{m.group(1)}`"
        owned.add((m.start(), m.start() + len(payload)))
    return frozenset(owned)


def _is_role_ref_or_target_payload(
    source: str,
    start: int,
    end: int,
    *,
    owned_payloads: frozenset[tuple[int, int]],
) -> bool:
    """True if bare `` `payload` `` at [start:end) is owned by role/ref/target grammar."""
    raw = source[start:end]
    if not (raw.startswith("`") and raw.endswith("`") and not raw.startswith("``")):
        return False
    if (start, end) in owned_payloads:
        return True
    # Named / anonymous reference: `payload`_ / `payload`__
    if end < len(source) and source[end] == "_":
        return True
    # Internal target: _`payload`
    if start >= 1 and source[start - 1] == "_":
        return True
    # Postfix role opener after payload (regex miss edge cases)
    if end < len(source) and source[end] == ":":
        if POSTFIX_ROLE_RE.match(source, start):
            return True
    return False


def _sentence_delimiter_offsets(
    pattern: re.Pattern[str],
    match: re.Match[str],
) -> tuple[int, ...]:
    """Return all source offsets whose escaping changes token ownership."""
    if pattern is _SENTENCE_LITERAL_RE:
        return (match.start(), match.end() - 2)
    if pattern is PREFIX_ROLE_RE:
        return (match.start(), match.start(2) - 1, match.end(2))
    if pattern is POSTFIX_ROLE_RE:
        return (match.start(), match.end(1))
    if pattern is INTERNAL_TARGET_RE:
        return (match.start(), match.start() + 1, match.end() - 1)
    if pattern is NAMED_REF_RE:
        return (match.start(), match.end(1))
    if pattern is SIMPLE_INTERP_RE:
        return (match.start(), match.end() - 1)
    if pattern is _SENTENCE_EMPHASIS_RE:
        return (match.start(), match.end() - 1)
    raise AssertionError(f"unknown sentence token pattern: {pattern.pattern}")


def _sentence_closed_token_offsets(
    source: str,
    opaque: list[tuple[int, int]],
    *,
    counters: OracleCounters,
) -> list[tuple[int, int]]:
    """Return closed token spans used only by SentenceView protection."""
    occupied = _occupied_mask(len(source), opaque)
    comment_mask = bytearray(len(source))
    counters.scan_chars += len(source)
    for _, line_start, line_end in _line_bounds(source):
        if _is_comment_line_at(source, line_start):
            _mark(comment_mask, line_start, line_end)
    ranges: list[tuple[int, int]] = []

    def claim(
        start: int,
        end: int,
        delimiter_offsets: tuple[int, ...],
    ) -> None:
        if comment_mask[start]:
            return
        if not _span_free(occupied, start, end):
            return
        _mark(occupied, start, end)
        if any(_is_markup_escaped(source, offset) for offset in delimiter_offsets):
            return
        ranges.append((start, end))

    patterns = (
        _SENTENCE_LITERAL_RE,
        PREFIX_ROLE_RE,
        POSTFIX_ROLE_RE,
        INTERNAL_TARGET_RE,
        NAMED_REF_RE,
        SIMPLE_INTERP_RE,
        _SENTENCE_EMPHASIS_RE,
    )
    for pattern in patterns:
        counters.scan_chars += len(source)
        for match in pattern.finditer(source):
            claim(
                match.start(),
                match.end(),
                _sentence_delimiter_offsets(pattern, match),
            )

    ranges.sort()
    return ranges


def _enumerate_candidates(
    source: str,
    opaque: list[tuple[int, int]],
    *,
    counters: OracleCounters,
    table_lines: frozenset[int],
) -> list[_RawCandidate]:
    counters.scan_chars += len(source)
    owned_payloads = _role_owned_payload_spans(source)
    # Account for the two role regex passes once (prefix + postfix)
    counters.scan_chars += len(source)

    # Precompute bare interpreted candidates per line once
    line_bare: dict[int, list[tuple[int, int]]] = {}
    for m in SIMPLE_INTERP_RE.finditer(source):
        start, end = m.start(), m.end()
        line_start = source.rfind("\n", 0, start) + 1
        line_bare.setdefault(line_start, []).append((start, end))
    counters.scan_chars += len(source)

    mask = _occupied_mask(len(source), [])
    candidates: list[_RawCandidate] = []

    def claim(start: int, end: int, form: str, raw: str) -> None:
        """Claim [start, end) for *form*. Always mask; emit only when repair needed."""
        if start < 0 or end > len(source) or start >= end:
            return
        if range_in_opaque(start, end, opaque):
            return
        if _is_comment_line_at(source, start):
            return
        if not _span_free(mask, start, end):
            return
        # Higher-priority forms always occupy the mask so later passes cannot
        # re-match their interiors (e.g. role payload as interpreted).
        _mark(mask, start, end)
        if form == "literal" and _literal_destroys_strong_or_emphasis(source, start, end):
            return
        # Shared-boundary mixed run (`x``-v``): equal-score → unsupported, not accepted.
        if form == "literal" and is_shared_boundary_literal(source, start, end):
            candidates.append(
                _RawCandidate(
                    start=start,
                    end=end,
                    form=form,
                    raw=raw,
                    edit_start=start,
                    edit_end=end,
                    expected_rawsource=raw,
                    status="unsupported",
                    reason="ambiguous-backticks",
                )
            )
            return
        # Column-fixed simple/grid tables: never freeze boundary inserts as accepted.
        line_start = source.rfind("\n", 0, start) + 1
        if line_start in table_lines:
            if not _token_needs_repair(source, start, end, form=form):
                return
            candidates.append(
                _RawCandidate(
                    start=start,
                    end=end,
                    form=form,
                    raw=raw,
                    edit_start=start,
                    edit_end=end,
                    expected_rawsource=raw,
                    status="unsupported",
                    reason="table-column-layout",
                )
            )
            return
        if not _token_needs_repair(source, start, end, form=form):
            return
        edit_start, edit_end, expected = _expected_token_with_boundaries(source, start, end, raw, form=form)
        candidates.append(
            _RawCandidate(
                start=start,
                end=end,
                form=form,
                raw=raw,
                edit_start=edit_start,
                edit_end=edit_end,
                expected_rawsource=expected,
            )
        )

    # Order: longer/more specific forms first; claim always marks mask
    # 1. Literals
    for m in LITERAL_RE.finditer(source):
        if _is_markup_escaped(source, m.start()):
            continue
        claim(m.start(), m.end(), "literal", m.group(0))

    # 2. Prefix roles
    for m in PREFIX_ROLE_RE.finditer(source):
        if _is_markup_escaped(source, m.start()):
            continue
        claim(m.start(), m.end(), "role_prefix", m.group(0))

    # 3. Postfix roles
    for m in POSTFIX_ROLE_RE.finditer(source):
        if _is_markup_escaped(source, m.start()):
            continue
        claim(m.start(), m.end(), "role_postfix", m.group(0))

    # 4. Internal targets (before named ref to claim _`...`)
    for m in INTERNAL_TARGET_RE.finditer(source):
        if _is_markup_escaped(source, m.start()):
            continue
        claim(m.start(), m.end(), "target_internal", m.group(0))

    # 5. Named / anonymous references
    for m in NAMED_REF_RE.finditer(source):
        if _is_markup_escaped(source, m.start()):
            continue
        claim(m.start(), m.end(), "ref_named" if m.group(2) == "_" else "ref_anonymous", m.group(0))

    # 6. Interpreted text — unique-owned only (not equal-score chains)
    for m in SIMPLE_INTERP_RE.finditer(source):
        start, end = m.start(), m.end()
        if not _span_free(mask, start, end):
            continue
        if range_in_opaque(start, end, opaque):
            continue
        if _is_comment_line_at(source, start):
            continue
        # Never treat role/ref/target payloads as interpreted (even if mask missed)
        if _is_role_ref_or_target_payload(source, start, end, owned_payloads=owned_payloads):
            _mark(mask, start, end)
            continue
        raw = m.group(0)
        line_start = source.rfind("\n", 0, start) + 1
        ambiguous_neighbor = False
        for abs_s, abs_e in line_bare.get(line_start, ()):
            if abs_s == start and abs_e == end:
                continue
            if range_in_opaque(abs_s, abs_e, opaque):
                continue
            if not _span_free(mask, abs_s, abs_e):
                continue
            if _is_role_ref_or_target_payload(source, abs_s, abs_e, owned_payloads=owned_payloads):
                continue
            if abs_e <= start:
                gap = source[abs_e:start]
            elif abs_s >= end:
                gap = source[end:abs_s]
            else:
                continue
            if gap and not any(ch.isspace() for ch in gap):
                ambiguous_neighbor = True
                break
        if ambiguous_neighbor:
            continue
        claim(start, end, "interpreted", raw)

    # 7. Null-escape normalization not already covered (e.g. before valid role)
    # Passes 1-6 are done, so freeze their edit ranges into a mask: the old
    # per-match `any(...)` over candidates was O(D^2) on `--fix` output.
    edit_mask = _occupied_mask(len(source), [(c.edit_start, c.edit_end) for c in candidates])
    for m in NULL_ESCAPE_RE.finditer(source):
        start, end = m.start(), m.end()
        # Line-initial `\ ` must stay untouched: normalizing it to ASCII space
        # would indent the line and change block structure (H-2 / block_quote).
        if _is_line_initial(source, start):
            continue
        if not _is_null_escape_before(source, end):
            continue
        if range_in_opaque(start, end, opaque):
            continue
        if _is_comment_line_at(source, start):
            continue
        if start < len(edit_mask) and edit_mask[start]:
            continue
        # Skip if this null-escape sits inside an already-claimed token span
        if start < len(mask) and mask[start]:
            continue
        adjacent = bool(
            PREFIX_ROLE_RE.match(source, end) or LITERAL_RE.match(source, end) or source.startswith("`", end)
        )
        if not adjacent and _ROLE_COLON_RE.match(source, end):
            adjacent = True
        if not adjacent:
            continue
        # Column-fixed simple/grid tables: normalizing `\ ` (2 chars) to a single
        # ASCII space shrinks the cell by one column and breaks the table.
        # Same responsibility boundary as the `claim` path above.
        if (source.rfind("\n", 0, start) + 1) in table_lines:
            candidates.append(
                _RawCandidate(
                    start=start,
                    end=end,
                    form="null_escape",
                    raw=m.group(0),
                    edit_start=start,
                    edit_end=end,
                    expected_rawsource=m.group(0),
                    status="unsupported",
                    reason="table-column-layout",
                )
            )
            continue
        candidates.append(
            _RawCandidate(
                start=start,
                end=end,
                form="null_escape",
                raw=m.group(0),
                edit_start=start,
                edit_end=end,
                expected_rawsource=" ",
            )
        )

    candidates.sort(key=lambda c: (c.edit_start, c.edit_end, c.start))
    return candidates


def _find_strong_owners(
    source: str,
    oracle_strong_ranges: list[tuple[int, int]],
    opaque: list[tuple[int, int]],
    *,
    counters: OracleCounters,
    table_lines: frozenset[int],
    newlines: list[int] | None = None,
    truncated_from_line: int | None = None,
) -> list[StrongOwner]:
    counters.scan_chars += len(source)
    owners: list[StrongOwner] = []
    seen: set[tuple[int, int]] = set()

    # Docutils-recognized strong first
    for start, end in oracle_strong_ranges:
        if (start, end) in seen:
            continue
        if end - start < 4:
            continue
        interior = (start + 2, end - 2)
        owners.append(
            StrongOwner(
                source_range=make_source_range(source, start, end, newlines=newlines),
                interior_range=make_source_range(source, interior[0], interior[1], newlines=newlines),
                recognized_by_docutils=True,
            )
        )
        seen.add((start, end))

    # Precompute literal spans once for containment checks
    literal_spans = [(lm.start(), lm.end()) for lm in LITERAL_RE.finditer(source)]
    counters.scan_chars += len(source)

    # Role/ref/target owned spans: ** inside their payloads is plain text.
    guarded_spans: list[tuple[int, int]] = list(_role_owned_payload_spans(source))
    guarded_spans.extend((m.start(), m.end()) for m in NAMED_REF_RE.finditer(source))
    guarded_spans.extend((m.start(), m.end()) for m in INTERNAL_TARGET_RE.finditer(source))
    counters.scan_chars += len(source)

    literal_index = _containment_index(literal_spans)
    guarded_index = _containment_index(guarded_spans)
    oracle_strong_index = _containment_index(oracle_strong_ranges)

    # Boundary-deficient outer **...** grammar
    for m in STRONG_RE.finditer(source):
        start, end = m.start(), m.end()
        # Alignment stopped before this point, so `oracle_strong_ranges` is
        # incomplete here and the grammar cannot tell a real outer strong from
        # an inner fragment. Fail closed rather than emit a guessed owner.
        if truncated_from_line is not None:
            if offset_to_line_column(source, start, newlines=newlines)[0] >= truncated_from_line:
                continue
        if _is_markup_escaped(source, start):
            continue
        interior_text = m.group(1)
        # STRONG_RE の (?!\s) が先頭空白を既に排除する。末尾空白のみここで拒否する。
        if interior_text[-1:].isspace():
            continue
        if (start, end) in seen:
            continue
        if range_in_opaque(start, end, opaque):
            continue
        # Skip fully-inside literal: ``**not-strong**``
        # `start - 1` turns the `ls <= start` query into the strict `ls < start`.
        if _span_covers(literal_index, start - 1, end):
            continue
        # Skip ** inside role/ref/target payloads and comment lines
        if _is_comment_line_at(source, start):
            continue
        # Column-fixed simple/grid tables: a boundary-deficient owner here would
        # let S4 insert outer spaces and shift the fixed columns. Mirrors the
        # InlineView table-column-layout decision. Docutils-recognized strong
        # (handled above) needs no boundary repair and stays an owner.
        if (source.rfind("\n", 0, start) + 1) in table_lines:
            continue
        if _span_covers(guarded_index, start, end):
            continue
        # Skip proper sub-spans of an oracle-recognized strong (**a**b**c**).
        # An exact match already exited at the `seen` check above, so plain
        # containment is equivalent to the proper-sub-span test here.
        if _span_covers(oracle_strong_index, start, end):
            continue
        interior = (start + 2, end - 2)
        owners.append(
            StrongOwner(
                source_range=make_source_range(source, start, end, newlines=newlines),
                interior_range=make_source_range(source, interior[0], interior[1], newlines=newlines),
                recognized_by_docutils=False,
            )
        )
        seen.add((start, end))

    owners.sort(key=lambda o: o.source_range.start)
    return owners


def _mark_overlapping(decisions: list[EditDecision]) -> list[EditDecision]:
    """Any group with overlapping edit ranges → all unsupported(overlapping-candidates)."""
    n = len(decisions)
    if n == 0:
        return decisions
    order = sorted(
        range(n),
        key=lambda i: (
            decisions[i].candidate.source_range.start,
            decisions[i].candidate.source_range.end,
        ),
    )
    overlap_ids: set[int] = set()
    cluster: list[int] = []
    cluster_end = -1
    for i in order:
        s = decisions[i].candidate.source_range.start
        e = decisions[i].candidate.source_range.end
        if cluster and s < cluster_end:
            cluster.append(i)
            cluster_end = max(cluster_end, e)
        else:
            if len(cluster) > 1:
                overlap_ids.update(cluster)
            cluster = [i]
            cluster_end = e
    if len(cluster) > 1:
        overlap_ids.update(cluster)
    if not overlap_ids:
        return decisions
    out: list[EditDecision] = []
    for i, d in enumerate(decisions):
        if i in overlap_ids:
            out.append(
                EditDecision(
                    candidate=d.candidate,
                    status="unsupported",
                    reason="overlapping-candidates",
                )
            )
        else:
            out.append(d)
    return out


def _is_plausible_asterisk_opener(
    source: str,
    start: int,
    width: int,
    line_start: int,
    line_end: int,
) -> bool:
    payload = start + width
    if payload >= line_end or source[payload].isspace() or source[payload] == "*":
        return False
    if start != line_start:
        before = source[start - 1]
        if not before.isspace() and _ASTERISK_START_BEFORE_RE.fullmatch(before) is None:
            return False

    # Exclude a numeric operator even when only its right-hand spacing is
    # missing ("2 *3"). Each backward walk covers only the immediately
    # preceding whitespace run, so the complete line scan stays linear.
    operand_end = start
    while operand_end > line_start and source[operand_end - 1].isspace():
        operand_end -= 1
    if source[payload].isdecimal() and operand_end > line_start and source[operand_end - 1].isdecimal():
        return False
    return True


def _footnote_marker_offset(source: str, start: int, end: int) -> int | None:
    segment = source[start:end].rstrip("\n")
    match = _ASTERISK_FOOTNOTE_RE.match(segment)
    if match is None:
        return None
    relative = segment.find("*", match.start(), match.end())
    return start + relative if relative >= 0 else None


def _unterminated_asterisk_lines(
    source: str,
    protected: tuple[SourceRange, ...],
    opaque: list[tuple[int, int]],
    *,
    table_lines: frozenset[int],
    counters: OracleCounters,
) -> frozenset[int]:
    """Return one-based lines with plausible unclosed * or ** openers."""
    protected_offsets = [(item.start, item.end) for item in protected]
    mask = _occupied_mask(len(source), [*opaque, *protected_offsets])
    unsupported: set[int] = set()
    counters.scan_chars += len(source)

    for line_no, line_start, line_end_with_nl in _line_bounds(source):
        if line_start in table_lines:
            continue
        line_end = (
            line_end_with_nl - 1
            if line_end_with_nl > line_start and source[line_end_with_nl - 1] == "\n"
            else line_end_with_nl
        )
        footnote_star = _footnote_marker_offset(source, line_start, line_end)
        pending: dict[int, int | None] = {1: None, 2: None}
        position = line_start

        while position < line_end:
            if source[position] != "*":
                position += 1
                continue
            run_end = position + 1
            while run_end < line_end and source[run_end] == "*":
                run_end += 1
            width = run_end - position

            if width not in (1, 2):
                position = run_end
                continue
            if footnote_star == position:
                position = run_end
                continue
            if _is_markup_escaped(source, position):
                position = run_end
                continue
            if any(mask[index] for index in range(position, run_end)):
                position = run_end
                continue

            opener = pending[width]
            if opener is not None and position > opener + width and not source[position - 1].isspace():
                pending[width] = None
            elif opener is None and _is_plausible_asterisk_opener(
                source,
                position,
                width,
                line_start,
                line_end,
            ):
                pending[width] = position
            position = run_end

        if any(opener is not None for opener in pending.values()):
            unsupported.add(line_no)

    return frozenset(unsupported)


def _ambiguous_interp_lines(source: str) -> frozenset[int]:
    """Lines with equal-score bare interpreted chains → unsupported for sentence."""
    lines: set[int] = set()
    for line_no, start, end in _line_bounds(source):
        segment = source[start:end]
        # x`a`y`b`z pattern: 2+ bare interps with alnum glue
        matches = list(SIMPLE_INTERP_RE.finditer(segment))
        bare = []
        for m in matches:
            after = segment[m.end() : m.end() + 2]
            before = segment[max(0, m.start() - 2) : m.start()]
            if after.startswith("_") or after.startswith(":"):
                continue
            if before.endswith(":") or before.endswith("_"):
                continue
            if PREFIX_ROLE_RE.search(segment[max(0, m.start() - 30) : m.end()]):
                # check if this match is the payload of a prefix role
                role_m = PREFIX_ROLE_RE.search(segment)
                if role_m and role_m.start() <= m.start() < role_m.end():
                    continue
            bare.append(m)
        for prev, cur in zip(bare, bare[1:], strict=False):
            gap = segment[prev.end() : cur.start()]
            # Zero-length gap is unreachable: SIMPLE_INTERP_RE's lookarounds
            # forbid adjacent matches, so the unguarded check here is safe.
            if not any(ch.isspace() for ch in gap):
                lines.add(line_no)
                break
    return frozenset(lines)


def classify_document(source: str) -> ConsumerViews:
    """Classify *source* into independent consumer views. No edits applied."""
    counters = OracleCounters()
    newlines = newline_offsets(source)
    oracle = parse_document(source, counters=counters)
    aligned, truncated_from_line = align_inlines_with_status(
        source, oracle.inlines, counters=counters, newlines=newlines
    )
    spans = aligned_to_spans(source, aligned, newlines=newlines)
    opaque = opaque_body_ranges(source, counters=counters)
    table_lines = _table_layout_line_starts(source)

    oracle_strong: list[tuple[int, int]] = []
    for a in aligned:
        if a.kind == "strong" and not range_in_opaque(a.start, a.end, opaque):
            oracle_strong.append((a.start, a.end))

    raw_candidates = _enumerate_candidates(source, opaque, counters=counters, table_lines=table_lines)
    decisions: list[EditDecision] = []
    for raw in raw_candidates:
        # Escaped / malformed gates
        if raw.form == "interpreted" and "\\" in raw.raw:
            decisions.append(
                EditDecision(
                    candidate=RepairCandidate(
                        source_range=make_source_range(source, raw.edit_start, raw.edit_end, newlines=newlines),
                        form=raw.form,
                        expected_rawsource=raw.expected_rawsource,
                    ),
                    status="rejected",
                    reason="escaped",
                )
            )
            continue
        candidate = RepairCandidate(
            source_range=make_source_range(source, raw.edit_start, raw.edit_end, newlines=newlines),
            form=raw.form,
            expected_rawsource=raw.expected_rawsource,
        )
        status = raw.status if raw.status in ("accepted", "rejected", "unsupported") else "accepted"
        decisions.append(
            EditDecision(
                candidate=candidate,
                status=status,
                reason=raw.reason,
            )
        )

    decisions = _mark_overlapping(decisions)

    owners = _find_strong_owners(
        source,
        oracle_strong,
        opaque,
        counters=counters,
        table_lines=table_lines,
        newlines=newlines,
        truncated_from_line=truncated_from_line,
    )

    # Sentence protection: aligned oracle spans + strong interiors (opaque excluded).
    # Unterminated / failed markup surfaces as problematic nodes; those are not
    # closed tokens and must not mask the asterisk unsupported-line scan.
    protected: list[SourceRange] = []
    for span in spans:
        if span.kind == "problematic":
            continue
        if not range_in_opaque(span.source_range.start, span.source_range.end, opaque):
            protected.append(span.source_range)
    for owner in owners:
        if not range_in_opaque(owner.interior_range.start, owner.interior_range.end, opaque):
            protected.append(owner.interior_range)
    for start, end in _sentence_closed_token_offsets(
        source,
        opaque,
        counters=counters,
    ):
        protected.append(make_source_range(source, start, end, newlines=newlines))
    # de-dup by start/end
    seen_p: set[tuple[int, int]] = set()
    uniq_protected: list[SourceRange] = []
    for p in sorted(protected, key=lambda r: (r.start, r.end)):
        key = (p.start, p.end)
        if key not in seen_p:
            seen_p.add(key)
            uniq_protected.append(p)

    unsupported: set[int] = set(_ambiguous_interp_lines(source))
    unsupported.update(
        _unterminated_asterisk_lines(
            source,
            tuple(uniq_protected),
            opaque,
            table_lines=table_lines,
            counters=counters,
        )
    )
    # Fail closed on partial alignment: from the truncation line onward the
    # oracle spans are unknown, so `protected` being empty must not read as
    # "nothing to protect" to sentence-breaks consumers.
    if truncated_from_line is not None:
        unsupported.update(line_no for line_no, _, _ in _line_bounds(source) if line_no >= truncated_from_line)
    # Unterminated/malformed backticks → mark line unsupported
    for line_no, start, end in _line_bounds(source):
        segment = source[start:end]
        # odd count of unescaped backticks (escaped = odd run of backslashes)
        ticks = 0
        i = 0
        while i < len(segment):
            if segment[i] == "`":
                n = 0
                j = i - 1
                while j >= 0 and segment[j] == "\\":
                    n += 1
                    j -= 1
                if n % 2 == 0:
                    ticks += 1
            i += 1
        if ticks % 2 == 1:
            unsupported.add(line_no)

    global _LAST_STATS
    _LAST_STATS = ClassificationStats(
        parse_count=counters.parse_count,
        scan_chars=counters.scan_chars,
    )

    return ConsumerViews(
        inline=InlineView(decisions=tuple(decisions)),
        strong=StrongView(owners=tuple(owners)),
        sentence=SentenceView(
            protected=tuple(uniq_protected),
            unsupported_lines=frozenset(unsupported),
        ),
    )


def _strong_boundary_matches_expected(source: str, expected: str, owner: StrongOwner) -> bool:
    """True if expected is source with external spaces around owner's ** pair.

    Accepts expected that differs from source only by inserting 0 or 1 ASCII
    space immediately before and/or after the owner's source_range token.
    Unrelated expected strings (different token or non-boundary edits) return False.
    """
    s, e = owner.source_range.start, owner.source_range.end
    token = source[s:e]
    if not token or token not in expected:
        return False

    # Walk every occurrence of the token in expected (handles rare duplicates).
    start = 0
    while True:
        idx = expected.find(token, start)
        if idx < 0:
            return False
        left = expected[:idx]
        right = expected[idx + len(token) :]
        # Strip at most one leading/trailing ASCII space adjacent to token
        # (the repair insert) and see if source is reconstructed.
        if left.endswith(" "):
            left_variants = (left, left[:-1])
        else:
            left_variants = (left,)
        if right.startswith(" "):
            right_variants = (right, right[1:])
        else:
            right_variants = (right,)
        for lv in left_variants:
            for rv in right_variants:
                if lv + token + rv == source:
                    return True
        start = idx + 1


def must_fix_is_accepted(source: str, expected: str | None, views: ConsumerViews) -> bool:
    """Return True if S2 classification supports a must_fix repair path.

    - Accepted EditDecision present for boundary/null-escape forms, or
    - Outer-strong-only repair covered by StrongOwner whose external boundary
      space insertion(s) alone produce ``expected``.
    """
    accepted = [d for d in views.inline.decisions if d.status == "accepted"]
    if accepted:
        return True
    if expected is None or not views.strong.owners:
        return False
    return any(_strong_boundary_matches_expected(source, expected, owner) for owner in views.strong.owners)
