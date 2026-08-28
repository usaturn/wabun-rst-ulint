"""Issue #15 regression corpus: bounded convergence for adjacent role/literal repairs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperationalConvergenceCase:
    id: str
    source: str
    first_expected: str
    fixed_point: str
    origin: str


def cases() -> tuple[OperationalConvergenceCase, ...]:
    return (
        OperationalConvergenceCase(
            id="issue15.role-literal-adjacent.bounded-convergence",
            source="値は:term:`X`と``code``です\n",
            first_expected="値は :term:`X` と``code``です\n",
            fixed_point="値は :term:`X` と ``code`` です\n",
            origin="https://github.com/usaturn/urst-checker/issues/15",
        ),
    )
