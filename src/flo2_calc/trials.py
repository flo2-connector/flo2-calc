"""The randomization test of an on/off trial: an exact p-value over every arrangement the scheme allows.

req:randomization-test-for-on-off-trials (levied from the cure design 2026-10-12, accepted 2026-10-13)
and dec:v0-8-0-bayes-randomization-shapley-choices, choices 3 and 5, in design 0bee0c00b35845f6.

randomization_test, args [outcomes, on]: a 1-D exact array, one outcome per period in the order
the periods ran, and a true/false array of the same length (true: the period was on). The node
names three things, none ever defaulted (evaluator.TRIAL_FIELDS), because the p-value rests on
how the trial was run and what it asks, which only the person and the agent know:

- "scheme", which assignments were possible. "every_arrangement": any arrangement of this many on
  periods among all of them, each equally likely: C(N, k) arrangements. "within_pairs": the
  periods in consecutive pairs (1-2, 3-4, ...), each pair one on and one off in a random order:
  2^(N/2) arrangements. The observed assignment must be one the scheme allows.
- "statistic": "mean_difference", the mean of the on periods minus the mean of the off periods.
- "alternative": "greater" (on minus off at least the observed), "less" (at most), or
  "two_sided" (at least as large either way).

The p-value is EXACT: the number of arrangements the scheme allows whose statistic is at least as
extreme as the observed one (the observed one among them), over the number of arrangements,
counted one by one. Never sampled. Every arrangement keeps the same number on, so the difference
of means rises with the on periods' sum: the outcomes are scaled to whole numbers by their
common denominator and each arrangement is one integer sum. The arrangements are counted
exactly BEFORE any is listed, and refused past the host's max_arrangements (limits.py); the
deadline is checked every CHUNK of them.
"""

from __future__ import annotations

import itertools
import math
from fractions import Fraction
from typing import Any, Callable, Iterable

from flo2_calc import arrays as A
from flo2_calc import evaluator as E
from flo2_calc import limits as L
from flo2_calc import units as U
from flo2_calc.errors import Refusal

CHUNK = 1 << 16


def _outcomes(op: str, value: Any, name: str) -> A.Array:
    if not isinstance(value, A.Array) or value.shape == ():
        what = "true/false" if isinstance(value, bool) else "a single value"
        raise Refusal(f'{op} takes the outcomes as a 1-D array, one per period, and "{name}" is {what}.', kind="type_mismatch")
    if value.data.ndim != 1:
        raise Refusal(f'{op} takes the outcomes as a 1-D array, one per period, and "{name}" is {A.shape_text(value.shape)}.', kind="shape_mismatch")
    if value.kind != A.EXACT:
        what = "a true/false array" if value.kind == A.BOOL else f"{value.kind} (not exact)"
        raise Refusal(f'{op} takes the outcomes as exact numbers, and "{name}" is {what}.', kind="type_mismatch")
    if U.scale_of(value.unit):
        raise Refusal(
            f'{op}: "{name}" holds temperature readings in {U.format_unit(value.unit)}; convert them to K first (a difference '
            "of means is a change of temperature).",
            kind="offset_temperature",
        )
    return value


def _assignment(op: str, value: Any, name: str, n: int, outcomes: str) -> list[bool]:
    if not isinstance(value, A.Array) or value.kind != A.BOOL or value.data.ndim != 1:
        raise Refusal(f'{op} takes which periods were on as a 1-D true/false array, and "{name}" is not one.', kind="type_mismatch")
    if value.size != n:
        raise Refusal(
            f'{op}: "{outcomes}" has {n} periods and "{name}" {value.size}; the outcomes and the assignment are the same length, '
            "one entry per period.",
            kind="shape_mismatch",
        )
    return [bool(x) for x in value.data.tolist()]


def _count(chunks: Iterable[list[Any]], hit: Callable[[Any], bool], guard: L.Guard) -> int:
    hits = 0
    for block in chunks:
        guard.check_time()
        hits += sum(1 for c in block if hit(c))
    return hits


def _chunked(it: Iterable[Any]) -> Iterable[list[Any]]:
    it = iter(it)
    while True:
        block = list(itertools.islice(it, CHUNK))
        if not block:
            return
        yield block


def apply(node: Any, args: list[Any], guard: L.Guard) -> E.Detailed:
    op, names = node.op, node.args
    y = _outcomes(op, args[0], names[0])
    n = y.size
    on = _assignment(op, args[1], names[1], n, names[0])
    k = sum(on)
    if k == 0 or k == n:
        raise Refusal(
            f'{op}: "{names[1]}" has {k} of {n} periods on; a difference of means needs at least one period on and at least '
            "one off.",
            kind="undefined",
        )
    if node.scheme == "within_pairs":
        if n % 2:
            raise Refusal(f'{op}: the within_pairs scheme takes the periods in pairs, so it needs an even number of them; "{names[0]}" has {n}.', kind="out_of_domain")
        for j in range(0, n, 2):
            if on[j] == on[j + 1]:
                raise Refusal(
                    f'{op}: under the within_pairs scheme each pair of periods is one on and one off, and periods {j + 1} and '
                    f'{j + 2} are both {"on" if on[j] else "off"}. State the scheme the trial actually used.',
                    kind="out_of_domain",
                )
        total = 1 << (n // 2)
        where = f"the within_pairs scheme over {n} periods ({n // 2} pairs)"
    else:
        total = math.comb(n, k)
        where = f"the every_arrangement scheme over {n} periods with {k} on"
    guard.check_arrangements(total, where)

    xs = y.data.tolist()
    scale = math.lcm(*(x.denominator for x in xs))
    ys = [int(x * scale) for x in xs]
    whole = sum(ys)
    observed_on = sum(v for v, o in zip(ys, on) if o)

    def statistic(sum_on: int) -> int:
        """The difference of means, times k (n - k) scale: an integer, rising with the on periods' sum."""
        return sum_on * n - k * whole

    w_obs = statistic(observed_on)
    tests: dict[str, Callable[[int], bool]] = {
        "greater": lambda s: s >= observed_on,
        "less": lambda s: s <= observed_on,
        "two_sided": lambda s: abs(statistic(s)) >= abs(w_obs),
    }
    extreme = tests[node.alternative]
    if node.scheme == "within_pairs":
        pairs = [(ys[j], ys[j + 1]) for j in range(0, n, 2)]
        hits = _count(_chunked(itertools.product(*pairs)), lambda c: extreme(sum(c)), guard)
    elif k <= n - k:
        hits = _count(_chunked(itertools.combinations(ys, k)), lambda c: extreme(sum(c)), guard)
    else:  # the fewer off periods are listed: the on sum is the rest
        hits = _count(_chunked(itertools.combinations(ys, n - k)), lambda c: extreme(whole - sum(c)), guard)
    observed = E.Quantity(Fraction(w_obs, k * (n - k) * scale), y.unit)
    detail = (("observed", observed), ("as_extreme", E.Quantity(Fraction(hits))), ("arrangements", E.Quantity(Fraction(total))))
    return E.Detailed(E.Quantity(Fraction(hits, total)), detail)
