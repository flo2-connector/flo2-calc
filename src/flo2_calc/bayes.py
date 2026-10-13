"""Bayesian updating of an estimate: a published population's prior, updated with a person's observations.

req:bayesian-update-of-an-estimate (levied from the cure design 2026-10-12, accepted 2026-10-13) and
dec:v0-8-0-bayes-randomization-shapley-choices, choices 1 and 2, in design 0bee0c00b35845f6.

NORMAL-NORMAL, a known observation sd. args [prior_mean, prior_sd, data, data_sd]: a normal prior
N(m0, s0^2) taken from a published population; the data one value or a 1-D exact array of n
observations, each with the known sd s; all in the prior mean's unit (each converted into it
exactly). The posterior is normal with

    mean     = (m0 s^2 + s0^2 sum(x)) / (s^2 + n s0^2)
    variance =  s0^2 s^2 / (s^2 + n s0^2)

the textbook precision-weighted form (1/s0^2 + n/s^2, and the weighted mean), rearranged so it
takes one division. Both are EXACT for exact inputs. posterior_normal_sd, the variance's square
root, is the rounded class: correctly rounded, exact where rational. The interval of a normal
posterior is normal_quantile([p, mean, sd]), which flo2-calc already has.

BETA-BINOMIAL. args [a, b, k, n]: a Beta(a, b) prior (a, b plain, > 0) and k successes in n trials
(exact whole numbers, 0 <= k <= n). The posterior is Beta(a', b'), a' = a + k and b' = b + n - k:
posterior_beta_a, posterior_beta_b, its mean a' / (a' + b') and variance a'b' / ((a' + b')^2
(a' + b' + 1)) are EXACT; its sd is rounded. posterior_beta_interval_lower and _upper, args
[a, b, k, n, level], give the EQUAL-TAILED credible interval: the posterior's beta_quantile at
(1 - level) / 2 and (1 + level) / 2, level never defaulted (req:skewed-distributions).

ROUNDED INPUTS carry their bounds through the evaluator's own arithmetic, so a result resting on
one is labelled rounded with a rigorous bound.

THE PRIOR'S SOURCE is checked when the graph is read (evaluator._check_prior_sources, PRIOR_ARGS
below): every input a prior argument rests on must carry a "source".
"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from typing import Any

from flo2_calc import arrays as A
from flo2_calc import decibels as D
from flo2_calc import evaluator as E
from flo2_calc import limits as L
from flo2_calc import realmath as RM
from flo2_calc import units as U
from flo2_calc.errors import Refusal

NORMAL = ("posterior_normal_mean", "posterior_normal_variance", "posterior_normal_sd")
BETA = ("posterior_beta_a", "posterior_beta_b", "posterior_beta_mean", "posterior_beta_variance", "posterior_beta_sd")
INTERVAL = ("posterior_beta_interval_lower", "posterior_beta_interval_upper")
# Each operator's prior arguments, by position, with what each is: every input they rest on needs a source.
PRIOR_ARGS: dict[str, tuple[tuple[int, str], ...]] = {
    **{op: ((0, "prior_mean"), (1, "prior_sd")) for op in NORMAL},
    **{op: ((0, "prior a"), (1, "prior b")) for op in BETA + INTERVAL},
}


def apply(node: Any, args: list[Any], guard: L.Guard) -> Any:
    if node.op in NORMAL:
        return _normal(node, args, guard)
    return _beta(node, args, guard)


def _step(node: Any, op: str, qs: list[Any], guard: L.Guard) -> Any:
    """One arithmetic step by the evaluator's own rules: exact on exact values,
    and on a rounded one the bound carried."""
    return E._arithmetic(replace(node, op=op, args=tuple(f"{node.id}.{op}{i}" for i in range(len(qs)))), qs, guard)


def _root(node: Any, q: Any, guard: L.Guard) -> Any:
    """The square root, in the rounded class: correctly rounded, exact where rational."""
    return E._function(replace(node, op="sqrt", args=(f"{node.id}.variance",)), [q], guard)


def _number(op: str, value: Any, name: str, role: str) -> Any:
    if isinstance(value, bool):
        raise Refusal(f'{op} takes the {role} as a number, and "{name}" is true/false.', kind="type_mismatch")
    if isinstance(value, A.Array):
        raise Refusal(f'{op} takes the {role} as one value, and "{name}" is an array.', kind="type_mismatch")
    return value


def _offset(op: str, unit: U.Unit, name: str) -> None:
    if U.scale_of(unit) or D.level_of(unit):
        raise Refusal(
            f'{op}: "{name}" is in {U.format_unit(unit)}, a scale with an offset (a temperature reading or a power level). '
            "Convert them to K first (or to W): a spread and a weighted mean are taken on a scale whose zero is zero.",
            kind="offset_temperature" if U.scale_of(unit) else "unit_mismatch",
            units=(U.format_unit(unit), ""),
        )


def _in_unit(q: Any, unit: U.Unit, op: str) -> Any:
    """q written in `unit` exactly (its bound scaled with it)."""
    f = U.conversion(q.unit, unit, op)
    rounding = q.rounding
    if rounding is not None and f != 1:
        rounding = E.Rounding(rounding.digits, rounding.error * f, rounding.correctly_rounded, rounding.origins)
    return E.Quantity(q.magnitude * f, unit, rounding)


def _data(op: str, value: Any, name: str, unit: U.Unit) -> tuple[list[Fraction], int]:
    """The observations in `unit`: one value, or a 1-D exact array of numbers."""
    if isinstance(value, bool):
        raise Refusal(f'{op} takes the data as numbers, and "{name}" is true/false.', kind="type_mismatch")
    if isinstance(value, E.Quantity):
        if value.rounding is not None:
            raise Refusal(f'{op} takes the data as exact observations, and "{name}" is a rounded value.', kind="type_mismatch")
        _offset(op, value.unit, name)
        return [value.magnitude * U.conversion(value.unit, unit, op)], 1
    assert isinstance(value, A.Array)
    if value.data.ndim != 1:
        raise Refusal(f'{op} takes the data as one value or a 1-D array, and "{name}" is {A.shape_text(value.shape)}.', kind="shape_mismatch")
    if value.kind == A.BOOL:
        raise Refusal(f'{op} takes the data as numbers, and "{name}" is a true/false array.', kind="type_mismatch")
    if value.kind != A.EXACT:
        raise Refusal(
            f'{op} takes the data as exact observations, and "{name}" is {value.kind} (an FFT, a function over an array, or '
            "an array past the host's max_exact_elements). Give the observations as written.",
            kind="type_mismatch",
        )
    if value.size == 0:
        raise Refusal(f'{op}: "{name}" holds no observations.', kind="undefined")
    _offset(op, value.unit, name)
    f = U.conversion(value.unit, unit, op)
    return [x * f for x in value.data.tolist()], value.size


def _normal(node: Any, args: list[Any], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    m0 = _number(op, args[0], names[0], "prior_mean")
    s0 = _number(op, args[1], names[1], "prior_sd")
    s = _number(op, args[3], names[3], "data_sd")
    unit = m0.unit
    _offset(op, unit, names[0])
    s0, s = _in_unit(s0, unit, op), _in_unit(s, unit, op)
    E._positive(op, s0, names[1], "the prior_sd, a standard deviation,")
    E._positive(op, s, names[3], "the data_sd, a standard deviation,")
    xs, n = _data(op, args[2], names[2], unit)
    total = sum(xs, Fraction(0))
    guard.check_number(total, "sum of the data")
    sum_x, count = E.Quantity(total, unit), E.Quantity(Fraction(n))
    s0_sq, s_sq = _step(node, "mul", [s0, s0], guard), _step(node, "mul", [s, s], guard)
    denominator = _step(node, "add", [s_sq, _step(node, "mul", [count, s0_sq], guard)], guard)
    detail: list[tuple[str, Any]] = [("n", count)]
    if op == "posterior_normal_mean":
        numerator = _step(node, "add", [_step(node, "mul", [m0, s_sq], guard), _step(node, "mul", [s0_sq, sum_x], guard)], guard)
        detail.append((f"sum({names[2]})", sum_x))
        return E.Detailed(_step(node, "div", [numerator, denominator], guard), tuple(detail))
    variance = _step(node, "div", [_step(node, "mul", [s0_sq, s_sq], guard), denominator], guard)
    if op == "posterior_normal_variance":
        return E.Detailed(variance, tuple(detail))
    detail.append(("variance", variance))
    return E.Detailed(_root(node, variance, guard), tuple(detail))


def _beta(node: Any, args: list[Any], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    a = E._fold(E._plain(op, _number(op, args[0], names[0], "prior a"), names[0], "a, a plain number (the prior's first parameter)"))
    b = E._fold(E._plain(op, _number(op, args[1], names[1], "prior b"), names[1], "b, a plain number (the prior's second parameter)"))
    E._positive(op, a, names[0], "a")
    E._positive(op, b, names[1], "b")
    k = E._whole_number(op, _number(op, args[2], names[2], "k"), names[2], "k, a count of successes")
    n = E._whole_number(op, _number(op, args[3], names[3], "n"), names[3], "n, a number of trials")
    if k > n:
        raise Refusal(
            f'{op}: k ("{names[2]}") is {k}, more than n ("{names[3]}") = {n}; k is a count of successes from 0 to n.',
            kind="out_of_domain",
        )
    a2 = _step(node, "add", [a, E.Quantity(Fraction(k))], guard)
    b2 = _step(node, "add", [b, E.Quantity(Fraction(n - k))], guard)
    if op == "posterior_beta_a":
        return a2
    if op == "posterior_beta_b":
        return b2
    total = _step(node, "add", [a2, b2], guard)
    if op == "posterior_beta_mean":
        return _step(node, "div", [a2, total], guard)
    if op in ("posterior_beta_variance", "posterior_beta_sd"):
        spread = _step(node, "mul", [_step(node, "mul", [total, total], guard), _step(node, "add", [total, E.Quantity(Fraction(1))], guard)], guard)
        variance = _step(node, "div", [_step(node, "mul", [a2, b2], guard), spread], guard)
        if op == "posterior_beta_variance":
            return variance
        return E.Detailed(_root(node, variance, guard), (("variance", variance),))
    # the equal-tailed credible interval, from the posterior's quantiles
    level_q = E._fold(E._plain(op, _number(op, args[4], names[4], "level"), names[4], "the level, a plain number (0.95 for 95 %)"))
    level = E._ball(level_q)
    if (level.exact and not 0 < level.mid < 1) or level.hi <= 0 or level.lo >= 1:
        raise Refusal(
            f'{op}: the level "{names[4]}" is {E.value_text(level_q)}; a credible interval\'s level is strictly between 0 and 1 '
            "(0.95 for a 95 % interval).",
            kind="out_of_domain",
        )
    if level.lo <= 0 or level.hi >= 1:
        raise E._undecidable(f'{op}: the level "{names[4]}" may be 0 or 1 within its error bound', level_q)
    sign = -1 if op == "posterior_beta_interval_lower" else 1
    p = RM.Ball((1 + sign * level.mid) / 2, level.rad / 2)
    places = E._places(node, [a2, b2, level_q])
    out = RM.skewed_quantile("beta", p, [E._ball(a2), E._ball(b2)], places, guard)
    shown_p = E.Quantity(p.mid) if p.exact else E._settle(p.mid, U.PLAIN, p.rad, [level_q])
    detail = (("p", shown_p), ("posterior a", a2), ("posterior b", b2))
    return E.Detailed(E._outcome(out, U.PLAIN, node, [a2, b2, level_q], places), detail)
