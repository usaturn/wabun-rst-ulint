from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
from random import Random

import pytest

from tests.helpers.bounded_fixer import bounded_fixer
from wabun_rst_ulint.checkers import sentence_breaks
from wabun_rst_ulint.checkers import strong_emphasis_spacing as strong_spacing
from wabun_rst_ulint.checkers._inline_classifier import classify_document, last_classification_stats
from wabun_rst_ulint.checkers._inline_model import EditDecision, RepairCandidate, SourceRange

GENERATED_SEED = 1507
EXPECTED_PAIRWISE_CASE_COUNT = 32
EXPECTED_INTERACTION_CASE_COUNT = 10
EXPECTED_GENERATED_CASE_COUNT = 42

FACTOR_POOLS = (
    (
        "form",
        ("literal", "interpreted", "prefix_role", "suffix_role", "named_ref", "anonymous_ref", "internal_target"),
    ),
    ("escape", ("even", "odd")),
    ("adjacency", ("ja_ja", "ascii_ascii", "ja_ascii", "ascii_ja")),
    ("punctuation", ("none", "cjk", "ascii", "bracket")),
    ("payload", ("unique", "repeated_payload", "repeated_rawsource", "literal_looking")),
    ("asterisk", ("none", "emphasis", "strong", "long_run")),
)


@dataclass(frozen=True)
class FactorVector:
    form: str
    escape: str
    adjacency: str
    punctuation: str
    payload: str
    asterisk: str

    @property
    def id(self) -> str:
        return ".".join((self.form, self.escape, self.adjacency, self.punctuation, self.payload, self.asterisk))


@dataclass(frozen=True)
class GeneratedCase:
    id: str
    source: str
    payloads: tuple[str, ...]
    delimiters: tuple[str, ...]
    interaction: str = "pairwise"


_FORM_PARTS = {
    "literal": ("``", "``"),
    "interpreted": ("`", "`"),
    "prefix_role": (":term:`", "`"),
    "suffix_role": ("`", "`:emphasis:"),
    "named_ref": ("`", "`_"),
    "anonymous_ref": ("`", "`__"),
    "internal_target": ("_`", "`"),
}
_ADJACENCY = {
    "ja_ja": ("前", "後"),
    "ascii_ascii": ("x", "y"),
    "ja_ascii": ("前", "y"),
    "ascii_ja": ("x", "後"),
}
_PUNCTUATION = {"none": "", "cjk": "。", "ascii": ".", "bracket": "）"}
_PAYLOAD = {
    "unique": "alpha",
    "repeated_payload": "same",
    "repeated_rawsource": "raw",
    "literal_looking": "code-like",
}
_ASTERISK = {"none": ("", ""), "emphasis": ("*", "*"), "strong": ("**", "**"), "long_run": ("***", "***")}


def _render_pairwise_case(vector: FactorVector) -> GeneratedCase:
    opening, closing = _FORM_PARTS[vector.form]
    left, right = _ADJACENCY[vector.adjacency]
    payload = _PAYLOAD[vector.payload]
    escape = "\\" if vector.escape == "odd" else "\\\\"
    outer_open, outer_close = _ASTERISK[vector.asterisk]
    markup = f"{opening}{payload}{closing}"
    primary = f"{left}{outer_open}{escape}{markup}{outer_close}{right}{_PUNCTUATION[vector.punctuation]}"
    if vector.payload == "repeated_payload":
        tail = f" and ``{payload}``"
    elif vector.payload == "repeated_rawsource":
        tail = f" and {markup}"
    elif vector.payload == "literal_looking":
        tail = " and ``code-like``"
    else:
        tail = ""
    return GeneratedCase(
        id=f"pairwise.{vector.id}",
        source=f"{primary}{tail}\n",
        payloads=(payload,),
        delimiters=(opening, closing),
    )


def test_generated_catalog_has_fixed_total_count():
    pairwise = tuple(_render_pairwise_case(vector) for vector in PAIRWISE_CASES)
    generated = (*pairwise, *INTERACTION_CASES)
    assert len(pairwise) == EXPECTED_PAIRWISE_CASE_COUNT
    assert len(INTERACTION_CASES) == EXPECTED_INTERACTION_CASE_COUNT
    assert len(generated) == EXPECTED_GENERATED_CASE_COUNT == 42
    assert len({case.id for case in generated}) == 42


def test_pairwise_catalog_has_fixed_seed_count_and_unique_ids():
    vectors = _select_pairwise_vectors()
    assert GENERATED_SEED == 1507
    assert len(vectors) == EXPECTED_PAIRWISE_CASE_COUNT == 32
    assert len({vector.id for vector in vectors}) == 32


FactorPair = tuple[str, str, str, str]


def _factor_pairs(vector: FactorVector) -> frozenset[FactorPair]:
    names = tuple(name for name, _ in FACTOR_POOLS)
    values = (
        vector.form,
        vector.escape,
        vector.adjacency,
        vector.punctuation,
        vector.payload,
        vector.asterisk,
    )
    return frozenset(
        (names[left], values[left], names[right], values[right]) for left, right in combinations(range(len(names)), 2)
    )


def _select_pairwise_vectors() -> tuple[FactorVector, ...]:
    candidates = [FactorVector(*values) for values in product(*(values for _, values in FACTOR_POOLS))]
    Random(GENERATED_SEED).shuffle(candidates)
    uncovered: set[FactorPair] = set().union(*(_factor_pairs(candidate) for candidate in candidates))
    selected: list[FactorVector] = []
    while uncovered:
        winner = max(candidates, key=lambda candidate: len(_factor_pairs(candidate) & uncovered))
        selected.append(winner)
        uncovered.difference_update(_factor_pairs(winner))
        candidates.remove(winner)
    return tuple(selected)


PAIRWISE_CASES = _select_pairwise_vectors()


INTERACTION_CASES = (
    GeneratedCase(
        "interaction.mandatory-unprovable",
        "値は``foo``ですと x`a`y`b`z 曖昧\n",
        ("foo", "a", "b"),
        ("``", "`"),
        "mandatory-unprovable",
    ),
    GeneratedCase("interaction.combined-proof", "本文 **``重要``** です\n", ("重要",), ("**", "``"), "combined-proof"),
    GeneratedCase(
        "interaction.repeated-payload",
        "``same`` と :term:`same` と `same`_\n",
        ("same",),
        ("``", ":term:`", "`_"),
        "repeated-payload",
    ),
    GeneratedCase(
        "interaction.repeated-rawsource",
        "値は``same``で、後も``same``です\n",
        ("same",),
        ("``",),
        "repeated-rawsource",
    ),
    GeneratedCase(
        "interaction.interpreted-literal",
        "値は`term`と``code``です\n",
        ("term", "code"),
        ("`", "``"),
        "interpreted-literal",
    ),
    GeneratedCase(
        "interaction.role-literal", "値は:term:`X`と``code``です\n", ("X", "code"), (":term:`", "``"), "role-literal"
    ),
    GeneratedCase(
        "interaction.reference-literal",
        "値は`ref`_と``code``です\n",
        ("ref", "code"),
        ("`_", "``"),
        "reference-literal",
    ),
    GeneratedCase(
        "interaction.outer-strong", "本文**a ``code`` b**です\n", ("a", "code", "b"), ("**", "``"), "outer-strong"
    ),
    GeneratedCase(
        "interaction.literal-looking",
        "``:term:`not-a-role``` と :term:`real`\n",
        ("not-a-role", "real"),
        ("``", ":term:`"),
        "literal-looking",
    ),
    GeneratedCase("interaction.overlap-synthetic", "x``ab``y\n", ("ab",), ("``",), "overlap-synthetic"),
)

PAIRWISE_GENERATED_CASES = tuple(_render_pairwise_case(vector) for vector in PAIRWISE_CASES)
GENERATED_CASES = (*PAIRWISE_GENERATED_CASES, *INTERACTION_CASES)
MULTI_PASS_CASE_IDS = frozenset(
    {
        "interaction.interpreted-literal",
        "interaction.role-literal",
        "interaction.reference-literal",
    }
)

# Frozen inline-spacing outcome per generated case, measured once from the
# behaviour of the reviewed implementation and written here as literals. Never
# recompute these from the code under test: they exist so that a fixer which
# emits one-sided boundaries -- or nothing at all -- fails the gate. ``None``
# means "no write": the combined projection proof rejects the repair and the
# source survives unchanged. For the three bounded-convergence ids in
# MULTI_PASS_CASE_IDS the value is the fixed point reached after round 2.
EXPECTED_OUTCOMES: dict[str, str | None] = {
    "pairwise.named_ref.odd.ascii_ja.ascii.repeated_rawsource.long_run": "x***\\`raw`_***後. and `raw`_\n",
    "pairwise.suffix_role.even.ja_ja.none.unique.strong": "前**\\\\`alpha`:emphasis: **後\n",
    "pairwise.internal_target.even.ascii_ascii.bracket.literal_looking.none": (
        "x\\\\_`code-like` y） and ``code-like``\n"
    ),
    "pairwise.anonymous_ref.odd.ja_ascii.cjk.repeated_payload.emphasis": "前*\\`same`__*y。 and ``same``\n",
    "pairwise.literal.even.ja_ja.cjk.literal_looking.long_run": None,
    "pairwise.interpreted.odd.ja_ja.none.repeated_payload.none": "前\\`same`後 and ``same``\n",
    "pairwise.literal.odd.ascii_ascii.ascii.unique.emphasis": "x*\\``alpha``*y.\n",
    "pairwise.interpreted.even.ja_ascii.ascii.repeated_rawsource.strong": "前**\\\\`raw `**y. and ` raw`\n",
    "pairwise.prefix_role.even.ascii_ja.none.literal_looking.emphasis": None,
    "pairwise.internal_target.odd.ascii_ja.bracket.repeated_payload.strong": "x**\\_`same`**後） and ``same``\n",
    "pairwise.prefix_role.odd.ja_ascii.bracket.unique.long_run": "前***\\:term:`alpha`***y）\n",
    "pairwise.anonymous_ref.even.ascii_ja.cjk.unique.none": "x\\\\`alpha`__ 後。\n",
    "pairwise.named_ref.even.ja_ja.bracket.repeated_rawsource.emphasis": None,
    "pairwise.suffix_role.odd.ja_ascii.ascii.literal_looking.none": "前\\`code-like`:emphasis:y. and ``code-like``\n",
    "pairwise.prefix_role.even.ascii_ascii.cjk.repeated_rawsource.strong": None,
    "pairwise.suffix_role.even.ascii_ascii.none.repeated_payload.long_run": (
        "x***\\\\`same`:emphasis: ***y and ``same``\n"
    ),
    "pairwise.literal.even.ja_ascii.none.repeated_rawsource.none": "前\\\\``raw`` y and ``raw``\n",
    "pairwise.prefix_role.even.ja_ja.ascii.repeated_payload.none": None,
    "pairwise.anonymous_ref.odd.ja_ja.none.literal_looking.strong": "前**\\`code-like`__**後 and ``code-like``\n",
    "pairwise.interpreted.odd.ascii_ja.bracket.unique.long_run": "x***\\`alpha`***後）\n",
    "pairwise.named_ref.odd.ascii_ascii.none.repeated_payload.none": "x\\`same`_y and ``same``\n",
    "pairwise.internal_target.even.ja_ja.none.repeated_rawsource.long_run": None,
    "pairwise.anonymous_ref.odd.ascii_ascii.ascii.repeated_rawsource.long_run": "x***\\`raw`__***y. and `raw`__\n",
    "pairwise.named_ref.odd.ja_ascii.cjk.literal_looking.strong": "前**\\`code-like`_**y。 and ``code-like``\n",
    "pairwise.internal_target.even.ja_ascii.ascii.unique.emphasis": None,
    "pairwise.suffix_role.odd.ascii_ja.cjk.repeated_rawsource.emphasis": (
        "x*\\`raw`:emphasis:*後。 and `raw`:emphasis:\n"
    ),
    "pairwise.interpreted.odd.ascii_ascii.cjk.literal_looking.emphasis": "x*\\`code-like`*y。 and ``code-like``\n",
    "pairwise.literal.even.ascii_ja.bracket.repeated_payload.strong": None,
    "pairwise.suffix_role.odd.ja_ascii.bracket.repeated_rawsource.emphasis": (
        "前*\\`raw`:emphasis:*y） and `raw`:emphasis:\n"
    ),
    "pairwise.named_ref.even.ascii_ja.cjk.unique.long_run": None,
    "pairwise.anonymous_ref.odd.ja_ja.bracket.literal_looking.none": "前\\`code-like`__後） and ``code-like``\n",
    "pairwise.internal_target.odd.ja_ascii.cjk.literal_looking.strong": "前**\\_`code-like`**y。 and ``code-like``\n",
    "interaction.mandatory-unprovable": "値は ``foo`` ですと x`a`y`b`z 曖昧\n",
    "interaction.combined-proof": "本文 **``重要``** です\n",
    "interaction.repeated-payload": "``same`` と :term:`same` と `same`_\n",
    "interaction.repeated-rawsource": "値は ``same`` で、後も ``same`` です\n",
    "interaction.interpreted-literal": "値は `term` と ``code`` です\n",
    "interaction.role-literal": "値は :term:`X` と ``code`` です\n",
    "interaction.reference-literal": "値は `ref`_ と ``code`` です\n",
    "interaction.outer-strong": "本文**a ``code`` b**です\n",
    "interaction.literal-looking": None,
    "interaction.overlap-synthetic": "x ``ab`` y\n",
}


def test_pairwise_catalog_covers_every_cross_factor_pair():
    # Tautological today: _select_pairwise_vectors loops ``while uncovered`` and can only
    # return once every required pair is consumed. Kept as a guard for a future rewrite to
    # a bounded loop -- it is not evidence that the current selection covers anything.
    all_vectors = tuple(FactorVector(*values) for values in product(*(values for _, values in FACTOR_POOLS)))
    required = set().union(*(_factor_pairs(vector) for vector in all_vectors))
    actual = set().union(*(_factor_pairs(vector) for vector in PAIRWISE_CASES))
    assert actual == required


def test_every_generated_case_has_a_frozen_expected_outcome():
    assert set(EXPECTED_OUTCOMES) == {case.id for case in GENERATED_CASES}
    assert len(EXPECTED_OUTCOMES) == EXPECTED_GENERATED_CASE_COUNT == 42


def _non_whitespace(text: str) -> str:
    return "".join(character for character in text if not character.isspace())


@pytest.mark.parametrize("case", GENERATED_CASES, ids=lambda case: case.id)
def test_generated_cases_preserve_tokens_terminate_and_converge(case: GeneratedCase, monkeypatch):
    views = classify_document(case.source)
    stats = last_classification_stats()
    assert stats.parse_count == 1
    assert stats.scan_chars <= 64 * max(1, len(case.source))
    assert views.inline is not None
    assert views.strong is not None
    assert views.sentence is not None
    assert classify_document(case.source) == views

    fix = bounded_fixer(monkeypatch)
    inline_result = fix(case.source)

    duplicate_result = fix(case.source)
    assert duplicate_result == inline_result

    expected_outcome = EXPECTED_OUTCOMES[case.id]
    if inline_result.transaction_failure:
        assert expected_outcome is None
        assert inline_result.text == case.source
        assert inline_result.changed is False
        assert inline_result.diagnostic
        inline_fixed = case.source
    else:
        inline_fixed = inline_result.text
        assert _non_whitespace(inline_fixed) == _non_whitespace(case.source)
        second = fix(inline_fixed)
        if case.id in MULTI_PASS_CASE_IDS:
            assert second.transaction_failure is False
            assert second.changed is True
            assert _non_whitespace(second.text) == _non_whitespace(case.source)
            third = fix(second.text)
            assert third.transaction_failure is False
            assert third.text == second.text
            assert third.changed is False
            inline_fixed = second.text
        else:
            assert second.transaction_failure is False
            assert second.text == inline_fixed
            assert second.changed is False
        assert inline_fixed == expected_outcome

    strong_fixed = strong_spacing.fix_text(inline_fixed)
    assert _non_whitespace(strong_fixed) == _non_whitespace(inline_fixed)
    assert strong_spacing.fix_text(strong_fixed) == strong_fixed

    sentence_fixed = sentence_breaks.fix_text(strong_fixed)
    assert sentence_breaks.fix_text(sentence_fixed) == sentence_fixed
    for payload in case.payloads:
        assert sentence_fixed.count(payload) == case.source.count(payload)
    for delimiter in case.delimiters:
        assert sentence_fixed.count(delimiter) == case.source.count(delimiter)


def _interaction(case_id: str) -> GeneratedCase:
    return next(case for case in INTERACTION_CASES if case.id == case_id)


def test_mandatory_repair_survives_unprovable_neighbor(monkeypatch):
    case = _interaction("interaction.mandatory-unprovable")
    result = bounded_fixer(monkeypatch)(case.source)
    assert result.transaction_failure is False
    assert result.text == "値は ``foo`` ですと x`a`y`b`z 曖昧\n"


def test_valid_strong_wrapped_literal_is_a_safe_noop(monkeypatch):
    case = _interaction("interaction.combined-proof")
    result = bounded_fixer(monkeypatch)(case.source)
    assert result.transaction_failure is False
    assert result.changed is False
    assert result.text == case.source


def test_overlapping_candidate_group_is_entirely_unsupported():
    source = _interaction("interaction.overlap-synthetic").source
    left = EditDecision(RepairCandidate(SourceRange(0, 5, 1, 1), "literal", " ``a`` "), "accepted", "boundary-repair")
    right = EditDecision(RepairCandidate(SourceRange(3, 8, 1, 4), "literal", " ``b`` "), "accepted", "boundary-repair")
    from wabun_rst_ulint.checkers._inline_classifier import _mark_overlapping

    marked = _mark_overlapping([left, right])
    assert source == "x``ab``y\n"
    assert {(decision.status, decision.reason) for decision in marked} == {("unsupported", "overlapping-candidates")}


def test_recommended_consumer_sequence_reaches_a_fixed_point(monkeypatch):
    case = _interaction("interaction.outer-strong")
    fix = bounded_fixer(monkeypatch)
    first = strong_spacing.fix_text(fix(sentence_breaks.fix_text(case.source)).text)
    second = strong_spacing.fix_text(fix(sentence_breaks.fix_text(first)).text)
    assert first == second == "本文 **a ``code`` b** です\n"
