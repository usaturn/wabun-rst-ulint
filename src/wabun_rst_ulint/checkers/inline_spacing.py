"""transactional な inline-spacing checker/fixer (Issue #11 / S3)。

S2 (`_inline_classifier.classify_document`) の `InlineView` だけを消費し、
`accepted` な EditDecision のみを検査・修正する。StrongView / SentenceView は
それぞれ strong-spacing / sentence-breaks の責務でありここでは扱わない。

使用例::

    uv run wabun-rst-ulint inline-spacing docs/
    uv run wabun-rst-ulint inline-spacing --fix docs/
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from docutils import nodes

from wabun_rst_ulint.checkers import _checker_runner
from wabun_rst_ulint.checkers._inline_classifier import classify_document
from wabun_rst_ulint.checkers._inline_model import EditDecision
from wabun_rst_ulint.checkers._rst_oracle import (
    AlignedInline,
    OracleDocument,
    OracleInline,
    align_inlines_with_status,
    parse_document,
)
from wabun_rst_ulint.reporting import Violation

# --- system_message Counter（tests/helpers/rst_fingerprint.py の同等ロジックを複製。
# production コードは tests/ を import しない） ---

_SOURCE_LINE_PREFIX = re.compile(r"^(?:<[^>\n]+>|[A-Za-z0-9_./\\-]+):\d+(?::\d+)?:\s*")
_LEVEL_TYPE_WRAPPER = re.compile(r"^\((?:DEBUG|INFO|WARNING|ERROR|SEVERE)/\d+\)\s*")
_TITLE_LENGTH_MESSAGE = re.compile(r"^(Title (?:under|over)line too short\.)")


def normalize_message_body(
    body: str,
    *,
    message_aliases: tuple[tuple[str, str], ...] = (),
) -> str:
    """system_message 本文からソース/行ラッパーと不安定な id 情報を除去する。

    title-length warning については本文（タイトル＋adornment）を残す。
    message_aliases は title-length 本文に限り適用し、許可された境界空白差だけを
    同一視する（例: ``True`` と  ``True`` → 同じ canonical markup）。
    """
    text = body.strip()
    text = _SOURCE_LINE_PREFIX.sub("", text, count=1)
    text = _LEVEL_TYPE_WRAPPER.sub("", text, count=1)
    if _TITLE_LENGTH_MESSAGE.match(text) is not None and message_aliases:
        # 長い old から置換し、短い alias が長い slice の部分一致で壊さないようにする。
        for old, new in sorted(message_aliases, key=lambda pair: len(pair[0]), reverse=True):
            if old:
                text = text.replace(old, new)
    text = re.sub(r'\s*See "backrefs" attribute for IDs\.\s*', " ", text)
    text = re.sub(r"\bid[s]?\s*[:=]\s*[\"']?[a-z0-9-]+[\"']?", "", text, flags=re.I)
    return " ".join(text.split())


def message_key(
    node: nodes.system_message,
    *,
    message_aliases: tuple[tuple[str, str], ...] = (),
) -> tuple[int, str, str]:
    """system_message ノードの安定な multiset key。"""
    level = int(node["level"])
    msg_type = str(node["type"])
    body = normalize_message_body(node.astext(), message_aliases=message_aliases)
    return (level, msg_type, body)


def messages_counter(
    document: nodes.document,
    *,
    message_aliases: tuple[tuple[str, str], ...] = (),
) -> Counter[tuple[int, str, str]]:
    """文書内の system_message を key の Counter に集計する。

    message_aliases は title-length message の本文 alias 用。
    """
    return Counter(message_key(n, message_aliases=message_aliases) for n in document.findall(nodes.system_message))


def _message_aliases_for_decisions(
    source: str,
    decisions: tuple[EditDecision, ...],
) -> tuple[tuple[str, str], ...]:
    """accepted decision の現状/期待 slice を同一 canonical markup へ寄せる alias 列。"""
    aliases: list[tuple[str, str]] = []
    for decision in decisions:
        start = decision.candidate.source_range.start
        end = decision.candidate.source_range.end
        current = source[start:end]
        expected = decision.candidate.expected_rawsource
        canonical = expected.strip()
        aliases.append((current, canonical))
        aliases.append((expected, canonical))
    return tuple(aliases)


# --- Document fingerprint（combined projection proof の入力） ---

# tests/helpers/rst_fingerprint.py の _BLOCK_TAGS から system_message を除いた集合。
# system_message はメッセージ本文用の paragraph を内部に持つため block 種別列には含めない
# （(6) の message Counter と重複するうえ、修正で message が消えるたびに誤検知するため）。
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
    }
)


def _has_system_message_ancestor(node: nodes.Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.tagname == "system_message":
            return True
        parent = parent.parent
    return False


InlineKey = tuple[str, str, str]


def _inline_key(item: OracleInline | AlignedInline) -> InlineKey:
    return (item.kind, item.rawsource, item.visible_text)


def _inline_proof_inputs(
    inlines: tuple[OracleInline, ...],
) -> tuple[tuple[OracleInline, ...], tuple[InlineKey, ...]]:
    alignable: list[OracleInline] = []
    image_semantics: list[InlineKey] = []
    previous: OracleInline | None = None
    for item in inlines:
        embedded_target = (
            item.kind == "target"
            and previous is not None
            and previous.kind == "reference"
            and bool(item.rawsource)
            and item.rawsource in previous.rawsource
        )
        if item.kind == "image":
            image_semantics.append(_inline_key(item))
        elif not embedded_target:
            alignable.append(item)
        previous = item
    return tuple(alignable), tuple(image_semantics)


def _touches_ranges(
    start: int,
    end: int,
    ranges: tuple[tuple[int, int], ...],
) -> bool:
    return any(start < range_end and range_start < end for range_start, range_end in ranges)


def _candidate_markup_range(source: str, start: int, end: int) -> tuple[int, int]:
    """accepted candidate の source_range から外側の境界空白を除いた範囲を返す。

    `_inline_classifier._expected_token_with_boundaries` は `\\ ` null escape を
    飲み込むため source_range の先頭が `\\` から始まることがあるが、`\\` は
    isspace() ではないためこのループでは剥がされず、先頭の null escape 接頭辞は
    返り値の範囲に残ったままになる（例: `\\ ``a```）。これは意図した挙動であり
    安全側にしか作用しない: null escape は既にその前後の字句を分離しているため、
    直前に隣接するバッククォートが markup を分割することはあり得ず、
    `_split_guard_rejections` はこのケースで fail-closed に倒れるだけである
    （誤って書き込みを許可する方向には作用しない）。
    """
    while start < end and source[start].isspace():
        start += 1
    while end > start and source[end - 1].isspace():
        end -= 1
    return (start, end)


def _recognized_neighbor_owns_tick(
    pos: int,
    markup_start: int,
    markup_end: int,
    aligned_inline_ranges: tuple[AlignedInlineRange, ...],
) -> bool:
    return any(
        start <= pos < end and (end == markup_start or start == markup_end)
        for start, end, _kind in aligned_inline_ranges
    )


def _split_guard_rejections(
    source: str,
    original_ranges: tuple[tuple[int, int], ...],
    aligned_inline_ranges: tuple[AlignedInlineRange, ...] = (),
) -> dict[int, int]:
    """拒否するdecision indexから1-based lineへのmapを返す。

    candidate の markup 範囲（外側の境界空白を除く）の直前・直後に、他の active
    accepted candidate の markup に属さないバッククォートが隣接する場合、その edit
    は既存のマークアップ字句を切断するか、parse 不能なデリミタ run から markup を
    切り出すものであり、レンダリング意味を変えるため当該 decision を拒否する。
    docutils oracle の parse 成否には依存しない（誤 parse で巨大化したノードの正当な
    修復を拒否しないため）。アスタリスク系 markup は S4（Issue #12）の責務なので
    対象外。

    exemption は意図的に「他の *active accepted* candidate の markup に属する」場合
    だけに限定している。S2 は隣接するトークンを `overlapping-candidates` 理由で
    unsupported に分類することがあり、そのトークンが字句として well-formed でも
    markups（accepted のみ）には含まれないため exemption の対象にならない。
    結果としてこのガードの発火は隣接トークン間の連結子に依存する
    connector-dependent な挙動になる: half-width space や「と」のような連結子は
    両側を独立に accepted へ倒すため発火しないが、全角空白 / タブ / NBSP /
    `\\ ` null escape の連結子は隣接トークンを unsupported のまま残すため発火する。
    exemption を unsupported/overlapping-candidates 側にも広げる案は S3 の
    follow-up として認識しているが、別途 corpus 検証とレビューが必要なため
    ここでは行わない。

    さらに、baseline parse で独立に認識された正常 inline（problematic 以外）が
    いずれの S2 decision（accepted/rejected/unsupported）の source_range とも
    重ならず、かつ candidate の markup 範囲の境界ちょうどで終端・開始しており、
    その inline が隣接バッククォートを所有する場合も exempt する
    （例: ````a``:ref:`b`です``` の ````a`` ``）。所有関係は baseline の align
    結果（aligned_inline_ranges）だけで証明し、decision の source_range や
    candidate と重なる範囲、境界で接しない inline は対象外。baseline parse が
    健全なノードと認識しても、connector-dependent な unsupported 隣接トークンは
    unsupported decision の range と重なるため exemption にならず fail-closed の
    ままである。problematic ノードも metadata から除外されているため、
    `:ref:`a``b`` の stray tick や `` `a`_`b`_です `` の parse error artifact は
    exemption にならない。decision と重なる baseline inline への exemption 拡張は
    別途 corpus 検証とレビューが必要なためここでは行わない（S3 の follow-up）。

    拒否した decision を除くと隣接関係（accepted-neighbor exemption）が変わる
    場合があるため、新たな拒否がなくなるまで同じ純粋判定を反復する。
    """
    active = set(range(len(original_ranges)))
    rejected: dict[int, int] = {}
    progressed = True
    while progressed:
        progressed = False
        markups = {index: _candidate_markup_range(source, *original_ranges[index]) for index in active}
        newly_rejected: list[tuple[int, int]] = []
        for index in sorted(active):
            markup_start, markup_end = markups[index]
            for pos in (markup_start - 1, markup_end):
                owned_by_accepted_neighbor = any(
                    start <= pos < end for neighbor_index, (start, end) in markups.items() if neighbor_index != index
                )
                if (
                    0 <= pos < len(source)
                    and source[pos] == "`"
                    # accepted candidate の markup にのみ属す場合を exempt する
                    # （unsupported/overlapping-candidates の隣接トークンは対象外）。
                    and not owned_by_accepted_neighbor
                    # baseline で独立に認識された正常 inline が候補境界ちょうどで
                    # 終端・開始しており、隣接 tick を所有する場合も exempt。
                    and not _recognized_neighbor_owns_tick(
                        pos,
                        markup_start,
                        markup_end,
                        aligned_inline_ranges,
                    )
                ):
                    newly_rejected.append((index, source.count("\n", 0, pos) + 1))
                    break
        for index, line in newly_rejected:
            active.remove(index)
            rejected[index] = line
            progressed = True
    return rejected


AlignedInlineRange = tuple[int, int, str]


def _untouched_inline_fingerprint(
    source: str,
    inlines: tuple[OracleInline, ...],
    effect_ranges: tuple[tuple[int, int], ...],
) -> tuple[tuple[InlineKey, ...], int | None, tuple[AlignedInlineRange, ...]]:
    alignable, image_semantics = _inline_proof_inputs(inlines)
    aligned, truncated_from_line = align_inlines_with_status(source, alignable)
    untouched = tuple(
        _inline_key(item) for item in aligned if not _touches_ranges(item.start, item.end, effect_ranges)
    )
    aligned_ranges = tuple((item.start, item.end, item.kind) for item in aligned if item.kind != "problematic")
    return untouched + image_semantics, truncated_from_line, aligned_ranges


@dataclass(frozen=True)
class DocumentFingerprint:
    """combined projection proof の入力となる、1回のパース結果からの抽出情報。"""

    untouched_inlines: tuple[tuple[str, str, str], ...]
    blocks: tuple[str, ...]
    messages: Counter[tuple[int, str, str]]
    truncated_from_line: int | None
    # split guard 用の baseline metadata。prove_combined_projection の等値比較には含めない。
    aligned_inline_ranges: tuple[AlignedInlineRange, ...] = ()


def _document_fingerprint_from_oracle(
    source: str,
    oracle: OracleDocument,
    *,
    edit_ranges: tuple[tuple[int, int], ...] = (),
    message_aliases: tuple[tuple[str, str], ...] = (),
) -> DocumentFingerprint:
    """既にパース済みの oracle から proof 用 fingerprint を抽出する。"""
    document = oracle.document
    untouched, truncated_from_line, aligned_ranges = _untouched_inline_fingerprint(
        source,
        oracle.inlines,
        edit_ranges,
    )
    blocks = tuple(
        node.tagname
        for node in document.findall()
        if isinstance(node, nodes.Element) and node.tagname in _BLOCK_TAGS and not _has_system_message_ancestor(node)
    )
    return DocumentFingerprint(
        untouched_inlines=untouched,
        blocks=blocks,
        messages=messages_counter(document, message_aliases=message_aliases),
        truncated_from_line=truncated_from_line,
        aligned_inline_ranges=aligned_ranges,
    )


def build_document_fingerprint(
    source: str,
    *,
    edit_ranges: tuple[tuple[int, int], ...] = (),
    message_aliases: tuple[tuple[str, str], ...] = (),
) -> DocumentFingerprint:
    """source を1回パースし、proof に必要な情報を抽出する。

    edit_ranges（編集の効果範囲。exact range より広い場合がある）と重なる
    inline ノードは untouched_inlines から除外する（それは意図された変更そのものであり、
    baseline/projected 間の比較対象にしない）。
    """
    oracle = parse_document(source)
    return _document_fingerprint_from_oracle(
        source,
        oracle,
        edit_ranges=edit_ranges,
        message_aliases=message_aliases,
    )


# --- Edit plan（accepted decision からの projected_source 構築） ---


class OverlappingEditsError(ValueError):
    """accepted decisions が重複区間を持つ場合に送出する。

    S2 は overlap する candidate 群を既に unsupported に分類しているため、
    accepted 同士が重複するのは通常発生しない。防御的チェックとして残す。
    """


def accepted_decisions(decisions: tuple[EditDecision, ...]) -> tuple[EditDecision, ...]:
    """EditDecision 列から status == "accepted" のものだけを抽出する。"""
    return tuple(d for d in decisions if d.status == "accepted")


def _boundary_effect_range(
    source: str,
    start: int,
    end: int,
    *,
    expand_left: bool,
    expand_right: bool,
) -> tuple[int, int]:
    line_start = source.rfind("\n", 0, start) + 1
    newline = source.find("\n", end)
    line_end = len(source) if newline < 0 else newline
    if expand_left:
        while start > line_start and not source[start - 1].isspace():
            start -= 1
    if expand_right:
        while end < line_end and not source[end].isspace():
            end += 1
    return (start, end)


@dataclass(frozen=True)
class EditPlan:
    """accepted decisions から構築した batch edit の結果。"""

    text: str
    original_ranges: tuple[tuple[int, int], ...]
    projected_ranges: tuple[tuple[int, int], ...]
    original_effect_ranges: tuple[tuple[int, int], ...]
    projected_effect_ranges: tuple[tuple[int, int], ...]
    forms: tuple[str, ...]


def _collapse_replacement_seams(
    source: str,
    ordered: list[EditDecision],
    replacements: list[str],
) -> None:
    """replacement と未編集 gap の境界で、replacement 側の重複半角スペースだけを落とす。

    既存 gap 自体は削除しない。replacement が新規追加またはワイド空白から正規化した
    半角スペースだけを落とすため、編集区間外不変の契約を維持する。
    孤立 decision と列末 decision も対象。
    """
    for index, decision in enumerate(ordered):
        current = decision.candidate.source_range
        current_source = source[current.start : current.end]
        replacement = replacements[index]

        if (
            replacement.startswith(" ")
            and not current_source.startswith(" ")
            and current.start > 0
            and source[current.start - 1] == " "
        ):
            replacement = replacement[1:]
        if (
            replacement.endswith(" ")
            and not current_source.endswith(" ")
            and current.end < len(source)
            and source[current.end] == " "
        ):
            replacement = replacement[:-1]
        replacements[index] = replacement

    for index in range(1, len(ordered)):
        previous = ordered[index - 1].candidate.source_range
        current = ordered[index].candidate.source_range
        gap = source[previous.end : current.start]
        previous_source = source[previous.start : previous.end]
        current_source = source[current.start : current.end]

        if not gap and replacements[index - 1].endswith(" ") and replacements[index].startswith(" "):
            replacements[index] = replacements[index][1:]
            continue
        if gap.startswith(" ") and replacements[index - 1].endswith(" ") and not previous_source.endswith(" "):
            replacements[index - 1] = replacements[index - 1][:-1]
        if gap.endswith(" ") and replacements[index].startswith(" ") and not current_source.startswith(" "):
            replacements[index] = replacements[index][1:]


def apply_accepted_edits(source: str, decisions: tuple[EditDecision, ...]) -> EditPlan:
    """accepted な EditDecision から projected_source を1パスで構築する。

    decisions は accepted のみを含むこと（呼び出し側で accepted_decisions() 済みとする）。
    区間が重複する場合は OverlappingEditsError を送出する。

    2つの decision が隙間なく隣接し、前者の置換テキスト末尾と後者の置換テキスト先頭が
    ともに半角スペースの場合（双方が独立に同じ境界へスペースを挿入した場合）、
    二重スペースを避けるため後者の先頭スペースを1文字落として結合する。
    未編集 gap が既に半角スペースを持つ場合も、replacement が追加した重複分だけを落とす。

    各 decision について、元 slice と replacement の左右端で空白の有無が変わる側だけ、
    同一物理行の連続した非空白 run まで proof 除外範囲（effect range）を広げる。
    実際の置換範囲は original_ranges / projected_ranges のまま変えない。
    """
    ordered = sorted(decisions, key=lambda d: d.candidate.source_range.start)
    replacements = [d.candidate.expected_rawsource for d in ordered]
    cursor = 0
    for decision in ordered:
        start = decision.candidate.source_range.start
        if start < cursor:
            raise OverlappingEditsError(f"overlapping accepted edit at offset {start}")
        cursor = decision.candidate.source_range.end
    _collapse_replacement_seams(source, ordered, replacements)

    out: list[str] = []
    cursor = 0
    original_ranges: list[tuple[int, int]] = []
    projected_ranges: list[tuple[int, int]] = []
    effect_flags: list[tuple[bool, bool]] = []
    projected_offset = 0
    for decision, replacement in zip(ordered, replacements, strict=True):
        start = decision.candidate.source_range.start
        end = decision.candidate.source_range.end
        gap = source[cursor:start]
        current = source[start:end]
        left_changed = current[:1].isspace() != replacement[:1].isspace()
        right_changed = current[-1:].isspace() != replacement[-1:].isspace()
        effect_flags.append((left_changed, right_changed))
        out.append(gap)
        projected_offset += len(gap)
        proj_start = projected_offset
        out.append(replacement)
        projected_offset += len(replacement)
        original_ranges.append((start, end))
        projected_ranges.append((proj_start, projected_offset))
        cursor = end
    out.append(source[cursor:])
    text = "".join(out)
    original_effect_ranges = tuple(
        _boundary_effect_range(source, start, end, expand_left=left, expand_right=right)
        for (start, end), (left, right) in zip(original_ranges, effect_flags, strict=True)
    )
    projected_effect_ranges = tuple(
        _boundary_effect_range(text, start, end, expand_left=left, expand_right=right)
        for (start, end), (left, right) in zip(projected_ranges, effect_flags, strict=True)
    )
    return EditPlan(
        text=text,
        original_ranges=tuple(original_ranges),
        projected_ranges=tuple(projected_ranges),
        original_effect_ranges=original_effect_ranges,
        projected_effect_ranges=projected_effect_ranges,
        forms=tuple(decision.candidate.form for decision in ordered),
    )


# --- Combined projection proof ---


@dataclass(frozen=True)
class ProofResult:
    """combined projection proof の結果。"""

    ok: bool
    reason: str | None = None


def prove_combined_projection(baseline: DocumentFingerprint, projected: DocumentFingerprint) -> ProofResult:
    """baseline/projected の untouched inline 列・block 列・message Counter を比較する純粋な証明関数。

    Safety transaction の (3)(4)(5)(6) に対応する。
    """
    if baseline.truncated_from_line is not None or projected.truncated_from_line is not None:
        return ProofResult(ok=False, reason="inline alignment truncated; cannot prove safety, failing closed")
    if projected.untouched_inlines != baseline.untouched_inlines:
        return ProofResult(
            ok=False,
            reason="untouched inline markup changed (payload/delimiter/adjacent node not preserved)",
        )
    if projected.blocks != baseline.blocks:
        return ProofResult(ok=False, reason="block structure changed")
    increase = projected.messages - baseline.messages
    if increase:
        return ProofResult(ok=False, reason=f"system message count increased for keys: {sorted(increase.keys())}")
    return ProofResult(ok=True)


# --- Check / Fix オーケストレーション ---


def _decision_violation(source: str, decision: EditDecision) -> Violation:
    candidate = decision.candidate
    current = source[candidate.source_range.start : candidate.source_range.end]
    return Violation(
        line=candidate.source_range.line,
        kind=candidate.form,
        text=(f"{candidate.form} の外部境界空白が不正（{current!r} → {candidate.expected_rawsource!r}）"),
    )


@dataclass(frozen=True)
class CheckResult:
    """check_document() の結果。"""

    violations: tuple[Violation, ...]


@dataclass(frozen=True)
class FixResult:
    """fix_document() の結果。transaction_failure=True の場合 text は入力と同一。"""

    text: str
    changed: bool
    violations: tuple[Violation, ...]
    transaction_failure: bool
    diagnostic: str | None = None


def check_document(source: str) -> CheckResult:
    """source を検査し、accepted decision のみを violation として報告する。"""
    views = classify_document(source)
    accepted = accepted_decisions(views.inline.decisions)
    return CheckResult(violations=tuple(_decision_violation(source, d) for d in accepted))


def fix_document(source: str) -> FixResult:
    """source を修正する。combined projection proof に失敗した場合は無変更で返す。"""
    views = classify_document(source)  # parse #1（S2 の責務）
    accepted = accepted_decisions(views.inline.decisions)
    if not accepted:
        return FixResult(text=source, changed=False, violations=(), transaction_failure=False)

    ordered = sorted(accepted, key=lambda d: d.candidate.source_range.start)
    original_ranges = tuple(
        (decision.candidate.source_range.start, decision.candidate.source_range.end) for decision in ordered
    )

    baseline_oracle = parse_document(source)  # S3 baseline parse（最大2回のうち1回目）
    baseline_meta = _document_fingerprint_from_oracle(source, baseline_oracle)

    # split guard の exemption 対象は、いずれの S2 decision（accepted/rejected/
    # unsupported）の source_range とも重なりのない独立した baseline inline だけ。
    # baseline parse が健全と認識しても decision と重なる inline（例:
    # connector-dependent な unsupported 隣接トークン）は除外し fail-closed を保つ。
    decision_ranges = tuple(
        (decision.candidate.source_range.start, decision.candidate.source_range.end)
        for decision in views.inline.decisions
    )
    recognized_neighbors = tuple(
        item for item in baseline_meta.aligned_inline_ranges if not _touches_ranges(item[0], item[1], decision_ranges)
    )

    rejections = _split_guard_rejections(source, original_ranges, recognized_neighbors)
    safe = tuple(decision for index, decision in enumerate(ordered) if index not in rejections)
    if not safe:
        guard_line = min(rejections.values())
        all_violations = tuple(_decision_violation(source, decision) for decision in accepted)
        return FixResult(
            text=source,
            changed=False,
            violations=all_violations,
            transaction_failure=True,
            diagnostic=(
                "split guard refused to write: "
                f"accepted edit would split an existing inline near line {guard_line}; failing closed"
            ),
        )

    violations = tuple(_decision_violation(source, decision) for decision in safe)
    message_aliases = _message_aliases_for_decisions(source, safe)

    try:
        plan = apply_accepted_edits(source, safe)
    except OverlappingEditsError as exc:
        return FixResult(
            text=source,
            changed=False,
            violations=violations,
            transaction_failure=True,
            diagnostic=f"overlapping accepted edits detected, refusing to write: {exc}",
        )

    baseline_fp = _document_fingerprint_from_oracle(
        source,
        baseline_oracle,
        edit_ranges=plan.original_effect_ranges,
        message_aliases=message_aliases,
    )
    projected_fp = build_document_fingerprint(
        plan.text,
        edit_ranges=plan.projected_effect_ranges,
        message_aliases=message_aliases,
    )  # S3 combined projection parse（最大2回のうち2回目）
    proof = prove_combined_projection(baseline_fp, projected_fp)
    if not proof.ok:
        return FixResult(
            text=source,
            changed=False,
            violations=violations,
            transaction_failure=True,
            diagnostic=f"combined projection proof failed, refusing to write: {proof.reason}",
        )

    return FixResult(
        text=plan.text,
        changed=True,
        violations=violations,
        transaction_failure=False,
    )


# --- CLI 未配線のエントリポイント（配線は #14） ---


def run(paths: Sequence[str | Path], *, fix: bool) -> int:
    """`_checker_runner` を使って対象ファイル群を検査・修正する。"""

    def process(text: str) -> _checker_runner.RunOutcome:
        if fix:
            result = fix_document(text)
            return _checker_runner.RunOutcome(
                violations=result.violations,
                fixed_text=result.text if result.changed else None,
                transaction_failure=result.transaction_failure,
                diagnostic=result.diagnostic,
            )
        result = check_document(text)
        return _checker_runner.RunOutcome(violations=result.violations)

    return _checker_runner.run_checker(paths, fix=fix, process=process)
