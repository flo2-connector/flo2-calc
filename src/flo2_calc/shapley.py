"""Shapley values: an outcome's credit shared among a few factors, from a table naming every combination.

req:shapley-credit-over-few-factors (levied from the cure design 2026-10-12, accepted 2026-10-13)
and dec:v0-8-0-bayes-randomization-shapley-choices, choices 4 and 5, in design 0bee0c00b35845f6.

shapley_values, args [outcomes]: a 1-D exact array of the outcome v(S) of every combination S of
k factors, present or absent: 2^k of them. The node names the factors, in order ("factors"), and,
for each outcome in turn, the factors present in it ("combinations", one list per outcome). The
table must name every combination exactly once: a factor not among "factors", a factor twice in
one combination, a combination named twice, or one not named at all, is a malformed call naming
it (read_table, when the graph is read). The agent and the person measure or model each outcome;
flo2-calc never fills one in.

Factor i's Shapley value is

    phi_i = sum over S not holding i of |S|! (k - |S| - 1)! / k! * (v(S + i) - v(S)),

EXACT for exact outcomes (the outcomes scaled to whole numbers by their common denominator, the
weights whole numbers over k!). The result is an exact 1-D array of the k values in the order of
"factors", in the outcomes' unit. The values always sum to v(all) - v(none) (efficiency), which
is checked exactly on every call and shown in the working, with each factor's value.

The table grows as 2^k, so the host sets the most factors it takes (max_shapley_factors,
limits.py): past it the call is stopped, naming the limit, before anything is computed.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any

from flo2_calc import arrays as A
from flo2_calc import evaluator as E
from flo2_calc import limits as L
from flo2_calc import units as U
from flo2_calc.errors import CallError, Refusal, at

CHECK_EVERY = 1 << 12


def _joined(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def describe(mask: int, factors: tuple[str, ...]) -> str:
    """A combination in words: which factors are present and which absent."""
    present = [f for j, f in enumerate(factors) if mask >> j & 1]
    absent = [f for j, f in enumerate(factors) if not mask >> j & 1]
    if not present:
        return f"no factor present ({_joined(absent)} all absent)"
    if not absent:
        return f"{_joined(present)} present (every factor)"
    return f"{_joined(present)} present, {_joined(absent)} absent"


def read_table(obj: dict[str, Any], op: str, path: str) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """The node's "factors" and "combinations", checked: every combination named exactly once.
    Raises CallError naming the field."""
    if op != "shapley_values":
        key = "factors" if "factors" in obj else "combinations"
        raise CallError(at(path, key), f'only shapley_values takes "{key}"; "{op}" does not.')
    for key in ("factors", "combinations"):
        if key not in obj:
            raise CallError(
                at(path, key),
                'shapley_values needs "factors" (the factors\' names, in the order their values come back) and '
                '"combinations" (for each outcome in turn, the list of the factors present in it).',
            )
    raw = obj["factors"]
    fpath = at(path, "factors")
    if not isinstance(raw, list) or not raw:
        raise CallError(fpath, "factors is a list of at least one factor's name.")
    factors: list[str] = []
    for i, f in enumerate(raw):
        if not isinstance(f, str) or not E.ID.match(f):
            raise CallError(at(fpath, i), "a factor's name is spelled as a node id: a letter or _, then up to 63 letters, digits, _ . or -.")
        if f in factors:
            raise CallError(at(fpath, i), f"{f!r} is named twice; name each factor once.")
        factors.append(f)
    k = len(factors)
    index = {f: j for j, f in enumerate(factors)}
    combos = obj["combinations"]
    cpath = at(path, "combinations")
    if not isinstance(combos, list):
        raise CallError(cpath, "combinations is a list with one entry per outcome: the list of the factors present in it.")
    seen: dict[int, int] = {}
    kept: list[tuple[str, ...]] = []
    for i, combo in enumerate(combos):
        here = at(cpath, i)
        if not isinstance(combo, list):
            raise CallError(here, 'each combination is a list of the factors present ([] for none), e.g. ["sleep", "diet"].')
        mask = 0
        for j, f in enumerate(combo):
            if not isinstance(f, str) or f not in index:
                raise CallError(at(here, j), f"{f!r} is not one of the factors ({', '.join(factors)}).")
            if mask >> index[f] & 1:
                raise CallError(at(here, j), f"{f!r} is named twice in this combination.")
            mask |= 1 << index[f]
        if mask in seen:
            raise CallError(
                here,
                f"this names the same combination as combinations[{seen[mask]}] ({describe(mask, tuple(factors))}): the "
                "table names each combination once, with its one outcome.",
            )
        seen[mask] = i
        kept.append(tuple(combo))
    size = 1 << k
    if len(seen) < size:
        missing = next(m for m in range(size) if m not in seen)
        raise CallError(
            cpath,
            f"the combination with {describe(missing, tuple(factors))} has no outcome: Shapley values need the outcome of "
            f"every one of the 2^{k} = {L.count_text(size)} combinations of {k} factors, and "
            f"{L.count_text(size - len(seen))} of the {L.count_text(size)} are not named. flo2-calc never fills one in: "
            "measure or model it, with the person.",
        )
    return tuple(factors), tuple(kept)


def apply(node: Any, args: list[Any], guard: L.Guard) -> E.Detailed:
    op, name = node.op, node.args[0]
    factors, combos = node.factors, node.combinations
    k = len(factors)
    guard.check_factors(k)
    v = args[0]
    if not isinstance(v, A.Array) or v.shape == ():
        what = "true/false" if isinstance(v, bool) else "a single value"
        raise Refusal(f'{op} takes the outcomes as a 1-D array, one per combination, and "{name}" is {what}.', kind="type_mismatch")
    if v.data.ndim != 1:
        raise Refusal(f'{op} takes the outcomes as a 1-D array, one per combination, and "{name}" is {A.shape_text(v.shape)}.', kind="shape_mismatch")
    if v.kind != A.EXACT:
        what = "a true/false array" if v.kind == A.BOOL else (
            f"{v.kind}: past this host's max_exact_elements ({guard.limits.max_exact_elements:,}) or computed in float64")
        raise Refusal(f'{op} takes exact outcomes, and "{name}" is {what}.', kind="type_mismatch")
    if U.scale_of(v.unit):
        raise Refusal(f'{op}: "{name}" holds temperature readings in {U.format_unit(v.unit)}; convert them to K first.', kind="offset_temperature")
    if v.size != len(combos):
        raise Refusal(
            f'{op}: "{name}" has {v.size} outcomes and the table names {len(combos)} combinations; each outcome is the one '
            "of the combination at the same place.",
            kind="shape_mismatch",
        )
    index = {f: j for j, f in enumerate(factors)}
    xs = v.data.tolist()
    scale = math.lcm(*(x.denominator for x in xs))
    table = [0] * (1 << k)
    for x, combo in zip(xs, combos, strict=True):
        table[sum(1 << index[f] for f in combo)] = int(x * scale)
    weights = [math.factorial(s) * math.factorial(k - s - 1) for s in range(k)]
    sums = [0] * k
    for mask in range(1 << k):
        if mask % CHECK_EVERY == 0:
            guard.check_time()
        w = weights[mask.bit_count()] if mask.bit_count() < k else 0
        base = table[mask]
        for i in range(k):
            if not mask >> i & 1:
                sums[i] += w * (table[mask | 1 << i] - base)
    whole = math.factorial(k) * scale
    phis = [Fraction(t, whole) for t in sums]
    for f, phi in zip(factors, phis, strict=True):
        guard.check_number(phi, f"Shapley value of {f}")
    v_all, v_none = Fraction(table[-1], scale), Fraction(table[0], scale)
    if sum(phis, Fraction(0)) != v_all - v_none:  # efficiency: an identity, so a failure is flo2-calc's own
        raise AssertionError(f"the Shapley values do not sum to v(all) - v(none) at node {node.id}")
    A.make_room(guard, (k,), A.EXACT)
    values = A._result(phis, (k,), v.unit, node, guard)
    unit = v.unit
    detail = tuple((f"phi({f})", E.Quantity(phi, unit)) for f, phi in zip(factors, phis, strict=True)) + (
        ("v(all)", E.Quantity(v_all, unit)),
        ("v(none)", E.Quantity(v_none, unit)),
        ("v(all) - v(none)", E.Quantity(v_all - v_none, unit)),
        ("sum of the values", E.Quantity(sum(phis, Fraction(0)), unit)),
    )
    return E.Detailed(values, detail)
