# Inline repair corpus (S1)

Executable contract data for the clean-slate inline-spacing redesign (Issue #8 / #9).
This package is **test-only**. Production checkers must not import it.

## Layout

| Module | Contents |
|--------|----------|
| `cases.py` | `InlineCorpusCase` schema, validation, supported-repair catalog + controls |
| `issue_4.py` / `issue_5.py` / `issue_6.py` | Provenance reproductions from GitHub Issues |
| `review_regressions.py` | PR #3 review categories (origin = PR URL, never ignored `reviews/`) |
| `parity_main.py` | One case per test in the four legacy modules |

Helpers live in `tests/helpers/rst_fingerprint.py` (parse, fingerprint, Counter message safety, alignment / opaque-role probes).

## Decision meanings

| decision | Runtime intent (enforced in later Issues) |
|----------|-------------------------------------------|
| `unchanged` | Silent, no edit, exit-neutral |
| `repairable` | Check reports violation; successful fix reaches `expected` |
| `diagnostic-only` | Non-fixing warning, no edit, exit-neutral |

Combined-proof failure is **not** a successful fix: no write, actionable diagnostic, exit 1.

## Adding a case

1. Choose a **stable unique** `id` (`catalog.*`, `issueN.*`, `parity.*`, `review.*`, `control.*`).
2. Set `decision` / `must_fix` / `expected` (required when repairable).
3. Set `origin` to a resolvable `https://github.com/usaturn/urst-checker/...` URL or a **tracked** repo path (not `reviews/` alone).
4. Put intentional redesign differences in `notes` — do not silently drop legacy tests.
5. Run:

```bash
uv run --isolated --with 'docutils==0.22.4' --with 'pytest>=8' pytest -q tests/test_inline_corpus.py
```

## Oracle version

Runtime dependency: `docutils>=0.22,<0.23`.
Locked / CI probe: `docutils==0.22.4`.

## Go/No-Go: must_fix AST/source alignment (Issue #8 / #9)

Metric (do **not** redefine):

1. `fingerprint(case.source)` only — never `case.expected` for the node list
2. order-preserving `align_inlines_to_source(source, inlines)`
3. empty inline lists = **fail**

S1 spike on docutils **0.22.4**: **30/55 ≈ 54.5%** (25 empty-inline sources).
Because rate < 100%, **S2 is blocked** until architecture is re-deliberated.
Do **not** downgrade `must_fix` cases to hide the gap.

## Maintenance rules

- `must_fix=True` cases are recall requirements for S2/S3 (keep them even when alignment fails).
- Message safety uses multiset `Counter` keys `(level, type, normalized_body)`.
- Never change production under `src/wabun_rst_ulint` in S1 PRs.
