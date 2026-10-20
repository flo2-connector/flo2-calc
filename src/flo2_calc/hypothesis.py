"""The named hypothesis tests, each a kept record: its statistic, p-value, sidedness, degrees of freedom, the
assumptions it rests on, and the decision at a stated alpha.

req:calc-computes-named-hypothesis-tests-as-kept-records (accepted 2026-10-19), option (a) of
dec:idea-how-a-statistical-hypothesis-test-is-designed-computed-and-read, in design 0bee0c00b35845f6; the
choices in dec:v0-10-0-named-test-and-power-choices.

THE TESTS, each an operator whose last argument is alpha, the significance level fixed in advance (an exact
plain number strictly between 0 and 1; a rounded one is refused, since a criterion is a number someone chose):

- z_test [data, mu0, sigma, alpha] or [mean, n, mu0, sigma, alpha]: H0 mu = mu0, sigma known.
- t_test_one_sample [data, mu0, alpha] or [mean, sd, n, mu0, alpha]: H0 mu = mu0, n - 1 degrees of freedom. A
  paired test is this test on the differences.
- t_test_two_sample [data1, data2, alpha] or [mean1, sd1, n1, mean2, sd2, n2, alpha]: H0 mu1 = mu2, with
  "variance" "welch" (unequal variances, Welch-Satterthwaite degrees of freedom) or "pooled" (equal variances,
  n1 + n2 - 2), never defaulted.
- chi2_goodness_of_fit [observed, expected, alpha]: counts against expected proportions (summing to 1) or
  expected counts (summing to the observed total), k - 1 degrees of freedom.
- chi2_independence [table, alpha]: an r x c table of counts, (r - 1)(c - 1) degrees of freedom; Pearson's X^2
  with no continuity correction.
- binomial_test [k, n, p0, alpha]: exact.
- fisher_exact [table, alpha]: a 2 x 2 table, exact, conditional on both margins.

Every test but the chi-square ones needs "alternative": "greater", "less" or "two_sided", never defaulted (a
chi-square test looks at the upper tail of X^2, which any departure from H0 raises, so it takes none).

THE P-VALUE is a computed probability, and the record says how it was computed. The z- and t-tests' are the
tail of the normal or Student-t distribution at the statistic, as an Arb function of EXACT arguments (the
statistic's square, its sign, the degrees of freedom: all rational for exact data), so it is CORRECTLY ROUNDED.
Welch's is the tail of Student's t at Welch's degrees of freedom, which is itself an approximation to the
statistic's distribution, and the record says so. The chi-square tests' is the chi-square tail, correctly
rounded: an approximation to the statistic's exact distribution, held to its condition, every expected count at
least 5 (Cochran), and REFUSED (kind "assumption_fails", naming the cell) when that fails rather than computed
anyway. The binomial and Fisher tests' are EXACT fractions: the sum over every outcome as or more extreme; two-
sided, every outcome no more probable than the one observed (the method of R's binom.test and fisher.test,
compared here exactly, not within a relative tolerance).

THE DECISION is "reject H0 at alpha = a" when p <= alpha, else "fail to reject H0 at alpha = a", decided on the
TRUE p-value (an enclosure that excludes alpha, at whatever precision that takes), never on the digits it is
shown to. Nothing here ever says H1 is shown, proven or true: reading a test's verdict is the design's job.

THE RECORD. The node's value is the p-value, with a DETAIL (the statistic, the degrees of freedom, n and
reject_H0) that its working step shows, and a "hypothesis_test" block (record schema 10): test, title, h0, h1,
alternative, sidedness, alpha (its node, value and source), n, statistic, dof (where there are any), p_value,
p_value_method, assumptions, decision, reject_h0, and variance for the two-sample t-test. Every test carries the
same fields: the class is pinned in tests/test_hypothesis.py.
"""

from __future__ import annotations

from fractions import Fraction
from math import comb
from typing import Any

from flo2_calc import arrays as A
from flo2_calc import decibels as D
from flo2_calc import evaluator as E
from flo2_calc import limits as L
from flo2_calc import realmath as RM
from flo2_calc import units as U
from flo2_calc.errors import CallError, Refusal, at

TESTS = ("z_test", "t_test_one_sample", "t_test_two_sample", "chi2_goodness_of_fit", "chi2_independence",
         "binomial_test", "fisher_exact")
# the argument counts each takes: the data, or its summary
ARG_COUNTS: dict[str, dict[int, str]] = {
    "z_test": {4: "[data, mu0, sigma, alpha]", 5: "[mean, n, mu0, sigma, alpha]"},
    "t_test_one_sample": {3: "[data, mu0, alpha]", 5: "[mean, sd, n, mu0, alpha]"},
    "t_test_two_sample": {3: "[data1, data2, alpha]", 7: "[mean1, sd1, n1, mean2, sd2, n2, alpha]"},
}
ALTERNATIVES = {
    "greater": "the parameter is above its H0 value (the upper tail)",
    "less": "the parameter is below its H0 value (the lower tail)",
    "two_sided": "the parameter differs from its H0 value either way (both tails)",
}
VARIANCES = {
    "welch": "Welch's test: the two variances are not assumed equal (Welch-Satterthwaite degrees of freedom)",
    "pooled": "Student's test: the two populations have equal variances, pooled (n1 + n2 - 2 degrees of freedom)",
}
CHI2 = ("chi2_goodness_of_fit", "chi2_independence")
MIN_EXPECTED = 5  # Cochran's condition for the chi-square approximation


# ---------------------------------------------------------------- reading a node's fields


def read_fields(obj: dict[str, Any], op: str, path: str, plans: dict[str, str]) -> tuple[str | None, str | None]:
    """A named test's (or a plan's) "alternative" and "variance": each required where it applies, named from its
    list, never defaulted, and refused on any other operator. `plans` maps each power and sample-size operator to
    the test it plans (power.py). randomization_test's own alternative is read by the evaluator."""
    test = plans.get(op, op)
    alternative = variance = None
    if test in TESTS and test not in CHI2:
        listed = "; ".join(f'"{k}" ({v})' for k, v in ALTERNATIVES.items())
        if "alternative" not in obj:
            raise CallError(
                at(path, "alternative"),
                f'{op} needs "alternative": {listed}. It is never defaulted: the p-value depends on it, and only the '
                "person and the agent know, before the data, which way the question looks.",
            )
        if obj["alternative"] not in ALTERNATIVES:
            raise CallError(at(path, "alternative"), f"{obj['alternative']!r} is not an alternative {op} has. It has: {listed}.")
        alternative = obj["alternative"]
    elif "alternative" in obj and op != "randomization_test":
        if test in CHI2:
            raise CallError(
                at(path, "alternative"),
                f'{op} takes no "alternative": a chi-square test looks at the upper tail of X^2, which any departure '
                "from H0, in any cell, raises.",
            )
        raise CallError(at(path, "alternative"), f'only randomization_test, the named tests and their plans take "alternative"; "{op}" does not.')
    if test == "t_test_two_sample":
        listed = "; ".join(f'"{k}" ({v})' for k, v in VARIANCES.items())
        if "variance" not in obj:
            raise CallError(
                at(path, "variance"),
                f'{op} needs "variance": {listed}. It is never defaulted: the two give different p-values, and whether '
                "the variances may be taken as equal is a judgement for the person and the agent.",
            )
        if obj["variance"] not in VARIANCES:
            raise CallError(at(path, "variance"), f"{obj['variance']!r} is not a variance {op} has. It has: {listed}.")
        variance = obj["variance"]
    elif "variance" in obj:
        raise CallError(at(path, "variance"), f'only the two-sample t-test and its plans take "variance"; "{op}" does not.')
    return alternative, variance


def check_arg_count(op: str, n: int, path: str) -> None:
    if op in ARG_COUNTS and n not in ARG_COUNTS[op]:
        forms = " or ".join(ARG_COUNTS[op].values())
        raise CallError(at(path, "args"), f'"{op}" takes the data or its summary: {forms}; this node gives {n} argument(s).')


# ---------------------------------------------------------------- reading arguments


def alpha_of(op: str, value: Any, name: str) -> E.Quantity:
    """alpha: an exact plain number strictly between 0 and 1 (a "%" folded in)."""
    if isinstance(value, bool) or isinstance(value, A.Array):
        raise Refusal(f'{op} takes alpha, the significance level, as one plain number, and "{name}" is not one.', kind="type_mismatch")
    q = E._fold(E._plain(op, value, name, "alpha, the significance level, a plain number (0.05)"))
    if q.rounding is not None:
        raise Refusal(
            f'{op}: alpha "{name}" is a rounded value ({E.value_text(q)}); a significance level is a number fixed in '
            "advance, so give it exactly (0.05, 1/100).",
            kind="out_of_domain",
        )
    if not 0 < q.magnitude < 1:
        raise Refusal(f'{op}: alpha "{name}" is {E.value_text(q)}; a significance level is strictly between 0 and 1.', kind="out_of_domain")
    return q


def one(op: str, value: Any, name: str, role: str) -> E.Quantity:
    """One exact value (not true/false, not an array, not rounded)."""
    if isinstance(value, bool):
        raise Refusal(f'{op} takes {role} as a number, and "{name}" is true/false.', kind="type_mismatch")
    if isinstance(value, A.Array):
        raise Refusal(f'{op} takes {role} as one value, and "{name}" is an array.', kind="type_mismatch")
    if value.rounding is not None:
        raise Refusal(
            f'{op} takes {role} exactly, and "{name}" is a rounded value ({E.value_text(value)}). Give the number as '
            "measured or published, or the data themselves (from which the test computes it exactly).",
            kind="type_mismatch",
        )
    _offset(op, value.unit, name)
    return value


def _offset(op: str, unit: U.Unit, name: str) -> None:
    if U.scale_of(unit) or D.level_of(unit):
        raise Refusal(
            f'{op}: "{name}" is in {U.format_unit(unit)}, a scale with an offset (a temperature reading or a power level). '
            "Convert it to K first (or to W): a mean difference and a spread are taken on a scale whose zero is zero.",
            kind="offset_temperature" if U.scale_of(unit) else "unit_mismatch",
            units=(U.format_unit(unit), ""),
        )


def sample(op: str, value: Any, name: str) -> tuple[list[Fraction], U.Unit]:
    """A 1-D exact array of observations, and its unit."""
    if isinstance(value, bool) or not isinstance(value, A.Array):
        what = "true/false" if isinstance(value, bool) else "a single value"
        raise Refusal(f'{op} takes the data as a 1-D array of observations, and "{name}" is {what}.', kind="type_mismatch")
    if value.data.ndim != 1:
        raise Refusal(f'{op} takes the data as a 1-D array, and "{name}" is {A.shape_text(value.shape)}.', kind="shape_mismatch")
    if value.kind != A.EXACT:
        what = "a true/false array" if value.kind == A.BOOL else f"{value.kind} (not exact)"
        raise Refusal(f'{op} takes the observations as exact numbers, as written, and "{name}" is {what}.', kind="type_mismatch")
    _offset(op, value.unit, name)
    return list(value.data.tolist()), value.unit


def counts(op: str, value: Any, name: str, ndim: int, what: str) -> list[Any]:
    """An exact plain array of whole counts >= 0, of `ndim` dimensions."""
    if isinstance(value, bool) or not isinstance(value, A.Array):
        raise Refusal(f'{op} takes {what} as an array of counts, and "{name}" is not an array.', kind="type_mismatch")
    if value.data.ndim != ndim:
        raise Refusal(f'{op} takes {what}, and "{name}" is {A.shape_text(value.shape)}.', kind="shape_mismatch")
    if value.kind != A.EXACT or value.unit != U.PLAIN:
        raise Refusal(f'{op} takes {what} as exact plain counts, and "{name}" is not.', kind="type_mismatch")
    flat = value.data.ravel().tolist()
    for i, x in enumerate(flat):
        if x.denominator != 1 or x < 0:
            raise Refusal(
                f'{op}: "{name}" holds {E._number_text(x)} at {A.index_text(i, value.shape)}; every count is a whole number of '
                "at least 0.",
                kind="out_of_domain",
            )
    return [int(x) for x in flat] if ndim == 1 else [[int(x) for x in row] for row in value.data.tolist()]


def whole(op: str, value: Any, name: str, what: str, least: int) -> int:
    if isinstance(value, A.Array):
        raise Refusal(f'{op} takes {what} as one value, and "{name}" is an array.', kind="type_mismatch")
    return E._whole_number(op, value, name, what, least)


def proportion(op: str, value: Any, name: str, role: str, open_: bool = True) -> Fraction:
    """An exact plain probability: strictly between 0 and 1 (open_), or from 0 to 1."""
    q = E._fold(E._plain(op, one(op, value, name, role), name, f"{role}, a plain number"))
    x = q.magnitude
    if (open_ and not 0 < x < 1) or not 0 <= x <= 1:
        between = "strictly between 0 and 1" if open_ else "from 0 to 1"
        raise Refusal(f'{op}: {role} "{name}" is {E.value_text(q)}; it is a probability {between}.', kind="out_of_domain")
    return x


def mean_var(xs: list[Fraction]) -> tuple[Fraction, Fraction]:
    n = len(xs)
    m = sum(xs, Fraction(0)) / n
    return m, sum(((x - m) ** 2 for x in xs), Fraction(0)) / (n - 1)


# ---------------------------------------------------------------- the p-value, the decision, the block


def _rounded(fn: RM.Fn, args: list[Fraction], node: Any, unit: U.Unit, places: int, guard: L.Guard) -> E.Quantity:
    exact = fn.exact(*args)
    if exact is not None:
        guard.check_number(exact)
        return E.Quantity(exact, unit)
    c = RM.correctly_rounded_by(RM.fn_at(fn, args), places, guard, fn.name)
    return E.Quantity(c, unit, E.Rounding(places, RM.half_unit(c, places), True, (node.id,)))


def signed_root(x2: Fraction, s: int, node: Any, unit: U.Unit, places: int, guard: L.Guard) -> E.Quantity:
    """s sqrt(x2): exact where rational, else correctly rounded (the statistic itself)."""
    root = RM.exact_sqrt(x2)
    if root is not None:
        return E.Quantity(s * root, unit)
    c = RM.correctly_rounded(RM.SQRT, [x2], places, guard)
    return E.Quantity(s * c, unit, E.Rounding(places, RM.half_unit(c, places), True, (node.id,)))


def decide(p: E.Quantity, fn: RM.Fn | None, args: list[Fraction], alpha: Fraction, guard: L.Guard) -> bool:
    """reject H0 when the TRUE p-value is at most alpha: exact p compared exactly; a rounded one decided from
    enclosures of the true value, at whatever precision that takes."""
    if p.rounding is None:
        return p.magnitude <= alpha
    assert fn is not None
    return RM.compare_by(RM.fn_at(fn, args), alpha, guard, "the decision at alpha") < 0


def _source_of(node: Any, name: str, nodes: dict[str, Any] | None) -> Any:
    if nodes is None:
        return None
    n = nodes.get(name)
    return getattr(n, "source", None) if n is not None and getattr(n, "op", None) is None else None


def finish(node: Any, *, title: str, h0: str, h1: str, sidedness: str, alpha_q: E.Quantity, n: list[int],
           statistic: tuple[str, E.Quantity], dof: E.Quantity | None, p: E.Quantity, method: str,
           assumptions: list[str], reject: bool, nodes: dict[str, Any] | None) -> E.Detailed:
    alpha_name = node.args[-1]
    written = E.value_json(alpha_q)
    decision = f"{'reject' if reject else 'fail to reject'} H0 at α = {written.get('exact') or written['value']}"
    alpha_block: dict[str, Any] = {"node": alpha_name, **written}
    src = _source_of(node, alpha_name, nodes)
    if src is not None:
        alpha_block["source"] = src
    block: dict[str, Any] = {
        "test": node.op,
        "title": title,
        "h0": h0,
        "h1": h1,
        "alternative": node.alternative or "upper_tail",
        "sidedness": sidedness,
        "alpha": alpha_block,
        "n": [str(k) for k in n],
        "statistic": statistic,
        "p_value": p,
        "p_value_method": method,
        "assumptions": assumptions,
        "decision": decision,
        "reject_h0": reject,
    }
    if node.variance is not None:
        block["variance"] = node.variance
    detail: list[tuple[str, Any]] = [(statistic[0], statistic[1])]
    if dof is not None:
        block["dof"] = dof
        detail.append(("dof", dof))
    detail.extend((f"n{i + 1}" if len(n) > 1 else "n", E.Quantity(Fraction(k))) for i, k in enumerate(n))
    detail.append(("reject_H0", reject))
    return E.Detailed(p, tuple(detail), ("hypothesis_test", block))


# ---------------------------------------------------------------- the tests


def apply(node: Any, args: list[Any], guard: L.Guard, nodes: dict[str, Any] | None = None) -> E.Detailed:
    op = node.op
    alpha_q = alpha_of(op, args[-1], node.args[-1])
    if op == "z_test":
        return _z(node, args, alpha_q, guard, nodes)
    if op in ("t_test_one_sample", "t_test_two_sample"):
        return _t(node, args, alpha_q, guard, nodes)
    if op in CHI2:
        return _chi2(node, args, alpha_q, guard, nodes)
    if op == "binomial_test":
        return _binomial(node, args, alpha_q, guard, nodes)
    return _fisher(node, args, alpha_q, guard, nodes)


def _sign(x: Fraction) -> int:
    return (x > 0) - (x < 0)


def _in_unit(op: str, q: E.Quantity, unit: U.Unit) -> Fraction:
    return q.magnitude * U.conversion(q.unit, unit, op)


def _z(node: Any, args: list[Any], alpha_q: E.Quantity, guard: L.Guard, nodes: Any) -> E.Detailed:
    op, names = node.op, node.args
    if len(args) == 4:
        xs, unit = sample(op, args[0], names[0])
        n = len(xs)
        mean = sum(xs, Fraction(0)) / n
        mu0, sigma = one(op, args[1], names[1], "mu0, the mean under H0"), one(op, args[2], names[2], "sigma, the known sd")
    else:
        m = one(op, args[0], names[0], "the sample mean")
        unit, mean = m.unit, m.magnitude
        n = whole(op, args[1], names[1], "n, the sample size", 1)
        mu0, sigma = one(op, args[2], names[2], "mu0, the mean under H0"), one(op, args[3], names[3], "sigma, the known sd")
    if n < 1:
        raise Refusal(f'{op}: the data hold no observations.', kind="undefined")
    m0 = _in_unit(op, mu0, unit)
    s = _in_unit(op, sigma, unit)
    if s <= 0:
        raise Refusal(f'{op}: sigma "{names[-2]}" is {E.value_text(sigma)}; a standard deviation must be greater than 0.', kind="out_of_domain")
    d = mean - m0
    z2 = d * d * n / (s * s)
    guard.check_number(z2, "the statistic")
    places = E._places(node, [])
    sign = _sign(d)
    fn = RM.z_p_value(node.alternative)
    fargs = [z2, Fraction(sign)]
    p = _rounded(fn, fargs, node, U.PLAIN, places, guard)
    reject = decide(p, fn, fargs, alpha_q.magnitude, guard)
    h1, side = {"greater": ("μ > μ0", "one-sided, upper tail"), "less": ("μ < μ0", "one-sided, lower tail"),
                "two_sided": ("μ ≠ μ0", "two-sided: a departure either way")}[node.alternative]
    return finish(
        node, title="z-test of one mean, the population sd known", h0="μ = μ0: the population mean is mu0", h1=h1,
        sidedness=side, alpha_q=alpha_q, n=[n], statistic=("z", signed_root(z2, sign, node, U.PLAIN, places, guard)),
        dof=None, p=p, nodes=nodes, reject=reject,
        method="the standard normal distribution of z = (mean - mu0) sqrt(n) / sigma under H0, its tail from Arb's erfc "
               "at the exact z^2, correctly rounded (exact at z = 0)",
        assumptions=[
            "the observations are independent",
            "sigma, the population sd, is known (given), not estimated from these data; if it was estimated, use t_test_one_sample",
            "the sample mean is normally distributed: the data are normal, or n is large enough for the central limit "
            "theorem (a judgement, not checked here)",
        ],
    )


def _t(node: Any, args: list[Any], alpha_q: E.Quantity, guard: L.Guard, nodes: Any) -> E.Detailed:
    op, names = node.op, node.args
    two = op == "t_test_two_sample"
    if not two:
        if len(args) == 3:
            xs, unit = sample(op, args[0], names[0])
            n = len(xs)
            if n < 2:
                raise Refusal(f'{op}: "{names[0]}" holds {n} observation; a t-test needs at least 2 (its sd has n - 1 degrees of freedom).', kind="undefined")
            mean, var = mean_var(xs)
            mu0 = one(op, args[1], names[1], "mu0, the mean under H0")
        else:
            m = one(op, args[0], names[0], "the sample mean")
            unit, mean = m.unit, m.magnitude
            sd = one(op, args[1], names[1], "the sample sd")
            n = whole(op, args[2], names[2], "n, the sample size", 2)
            var = _in_unit(op, sd, unit) ** 2
            mu0 = one(op, args[3], names[3], "mu0, the mean under H0")
        if var == 0:
            raise Refusal(f'{op}: the sample variance is 0 (every observation the same), so t is undefined.', kind="undefined")
        d = mean - _in_unit(op, mu0, unit)
        t2 = d * d * n / var
        nu = Fraction(n - 1)
        ns = [n]
        title = "one-sample t-test of a mean (Student)"
        h0, h1s = "μ = μ0: the population mean is mu0", ("μ > μ0", "μ < μ0", "μ ≠ μ0")
        method = (f"Student's t distribution with n - 1 = {n - 1} degrees of freedom, its tail as the regularized "
                  "incomplete beta (Arb) at the exact t^2, correctly rounded")
        assumptions = [
            "the observations are independent",
            "they come from a normal population (a judgement, not checked here; with a large n the test is robust to it)",
            "the sd is estimated from these data (n - 1)",
        ]
    else:
        if len(args) == 3:
            xs, unit = sample(op, args[0], names[0])
            ys, unit2 = sample(op, args[1], names[1])
            f = U.conversion(unit2, unit, op)
            ys = [y * f for y in ys]
            n1, n2 = len(xs), len(ys)
            for k, nm in ((n1, names[0]), (n2, names[1])):
                if k < 2:
                    raise Refusal(f'{op}: "{nm}" holds {k} observation; each sample needs at least 2.', kind="undefined")
            m1, v1 = mean_var(xs)
            m2, v2 = mean_var(ys)
        else:
            a = one(op, args[0], names[0], "the first sample's mean")
            unit = a.unit
            m1 = a.magnitude
            v1 = _in_unit(op, one(op, args[1], names[1], "the first sample's sd"), unit) ** 2
            n1 = whole(op, args[2], names[2], "n1, the first sample's size", 2)
            m2 = _in_unit(op, one(op, args[3], names[3], "the second sample's mean"), unit)
            v2 = _in_unit(op, one(op, args[4], names[4], "the second sample's sd"), unit) ** 2
            n2 = whole(op, args[5], names[5], "n2, the second sample's size", 2)
        d = m1 - m2
        ns = [n1, n2]
        if node.variance == "welch":
            u1, u2 = v1 / n1, v2 / n2
            if u1 + u2 == 0:
                raise Refusal(f"{op}: both samples' variances are 0, so t is undefined.", kind="undefined")
            t2 = d * d / (u1 + u2)
            nu = (u1 + u2) ** 2 / (u1 * u1 / (n1 - 1) + u2 * u2 / (n2 - 1))
            title = "two-sample t-test of two means, Welch's (variances not assumed equal)"
            method = ("Student's t distribution at Welch-Satterthwaite's degrees of freedom (exact for these data): "
                      "Welch's approximation to the statistic's distribution; that t tail as the regularized "
                      "incomplete beta (Arb), correctly rounded")
            var_assumption = "the two variances are not assumed equal (Welch)"
        else:
            sp2 = ((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)
            if sp2 == 0:
                raise Refusal(f"{op}: the pooled variance is 0 (every observation in each sample the same), so t is undefined.", kind="undefined")
            t2 = d * d / (sp2 * (Fraction(1, n1) + Fraction(1, n2)))
            nu = Fraction(n1 + n2 - 2)
            title = "two-sample t-test of two means, pooled (Student's: equal variances)"
            method = (f"Student's t distribution with n1 + n2 - 2 = {n1 + n2 - 2} degrees of freedom, its tail as the "
                      "regularized incomplete beta (Arb) at the exact t^2, correctly rounded")
            var_assumption = "the two populations have equal variances (pooled; a judgement, not checked here)"
        h0, h1s = "μ1 = μ2: the two population means are equal", ("μ1 > μ2", "μ1 < μ2", "μ1 ≠ μ2")
        assumptions = [
            "the two samples are independent of each other, and the observations within each are independent",
            "each comes from a normal population (a judgement, not checked here)",
            var_assumption,
        ]
    guard.check_number(t2, "the statistic")
    guard.check_number(nu, "the degrees of freedom")
    places = E._places(node, [])
    sign = _sign(d)
    fn = RM.t_p_value(node.alternative)
    fargs = [t2, nu, Fraction(sign)]
    p = _rounded(fn, fargs, node, U.PLAIN, places, guard)
    reject = decide(p, fn, fargs, alpha_q.magnitude, guard)
    h1 = dict(zip(("greater", "less", "two_sided"), h1s))[node.alternative]
    side = {"greater": "one-sided, upper tail", "less": "one-sided, lower tail", "two_sided": "two-sided: a departure either way"}[node.alternative]
    return finish(
        node, title=title, h0=h0, h1=h1, sidedness=side, alpha_q=alpha_q, n=ns,
        statistic=("t", signed_root(t2, sign, node, U.PLAIN, places, guard)), dof=E.Quantity(nu), p=p, method=method,
        assumptions=assumptions, reject=reject, nodes=nodes,
    )


def _expected_ok(op: str, expected: list[tuple[str, Fraction]]) -> None:
    low = [(where, e) for where, e in expected if e < MIN_EXPECTED]
    if low:
        where, e = low[0]
        others = f" (and {len(low) - 1} more)" if len(low) > 1 else ""
        alt = ("fisher_exact for a 2 x 2 table" if op == "chi2_independence"
               else "binomial_test for two categories")
        raise Refusal(
            f"{op}: the expected count at {where} is {E._number_text(e)}{others}, below {MIN_EXPECTED}; the chi-square "
            "distribution is then not a fair approximation to the statistic's (Cochran's condition: every expected count "
            f"at least {MIN_EXPECTED}), so flo2-calc gives no p-value from it. Collect more data, combine categories where "
            f"that is meaningful (your judgement), or use an exact test: {alt}.",
            kind="assumption_fails",
        )


def _chi2(node: Any, args: list[Any], alpha_q: E.Quantity, guard: L.Guard, nodes: Any) -> E.Detailed:
    op, names = node.op, node.args
    if op == "chi2_goodness_of_fit":
        obs = counts(op, args[0], names[0], 1, "the observed counts, one per category (a 1-D array)")
        k = len(obs)
        if k < 2:
            raise Refusal(f"{op}: a goodness-of-fit test needs at least 2 categories; \"{names[0]}\" has {k}.", kind="undefined")
        ev = args[1]
        if isinstance(ev, bool) or not isinstance(ev, A.Array) or ev.data.ndim != 1 or ev.kind != A.EXACT or ev.unit != U.PLAIN:
            raise Refusal(f'{op} takes the expected proportions (or counts) as a 1-D exact plain array, and "{names[1]}" is not one.', kind="type_mismatch")
        if ev.size != k:
            raise Refusal(f'{op}: "{names[0]}" has {k} categories and "{names[1]}" {ev.size}; one expected value per category.', kind="shape_mismatch")
        es = list(ev.data.tolist())
        total = sum(obs)
        if total == 0:
            raise Refusal(f'{op}: "{names[0]}" counts nothing.', kind="undefined")
        if any(e <= 0 for e in es):
            raise Refusal(f'{op}: every expected value in "{names[1]}" must be greater than 0.', kind="out_of_domain")
        s = sum(es, Fraction(0))
        if s == total:
            expected = es
        elif s == 1:
            expected = [e * total for e in es]
        else:
            raise Refusal(
                f'{op}: the expected values "{names[1]}" sum to {E._number_text(s)}: neither 1 (proportions) nor {total}, '
                "the observed total (counts). Give the proportions H0 states, exactly (1/4, not 0.25 rounded).",
                kind="out_of_domain",
            )
        _expected_ok(op, [(f"category {i + 1}", e) for i, e in enumerate(expected)])
        x2 = sum(((o - e) ** 2 / e for o, e in zip(obs, expected)), Fraction(0))
        df = k - 1
        n = [total]
        title = "chi-square goodness-of-fit test (Pearson)"
        h0 = "the categories occur in the proportions given"
        h1 = "they do not: some proportion differs"
        method = (f"the chi-square distribution with k - 1 = {df} degrees of freedom: an approximation to the "
                  f"statistic's exact distribution, held to its condition (every expected count at least {MIN_EXPECTED}, "
                  "checked); the tail correctly rounded (Arb's incomplete gamma)")
        assumptions = [
            "each observation is independent and falls in exactly one category",
            "the expected proportions were fixed in advance, not estimated from these data (if any parameter was "
            "estimated from them, the degrees of freedom are fewer and this p-value is wrong)",
            f"the chi-square approximation: every expected count at least {MIN_EXPECTED} (checked)",
        ]
    else:
        table = counts(op, args[0], names[0], 2, "a table of counts, rows by columns (a grid)")
        r, c = len(table), len(table[0])
        if r < 2 or c < 2:
            raise Refusal(f'{op}: a test of independence needs at least 2 rows and 2 columns; "{names[0]}" is {r} x {c}.', kind="shape_mismatch")
        rows = [sum(row) for row in table]
        cols = [sum(table[i][j] for i in range(r)) for j in range(c)]
        total = sum(rows)
        if 0 in rows or 0 in cols:
            raise Refusal(f'{op}: a row or column of "{names[0]}" counts nothing, so its expected counts are 0.', kind="undefined")
        expected = [[Fraction(rows[i] * cols[j], total) for j in range(c)] for i in range(r)]
        _expected_ok(op, [(f"row {i + 1}, column {j + 1}", expected[i][j]) for i in range(r) for j in range(c)])
        x2 = sum(((table[i][j] - expected[i][j]) ** 2 / expected[i][j] for i in range(r) for j in range(c)), Fraction(0))
        df = (r - 1) * (c - 1)
        n = [total]
        title = "chi-square test of independence (Pearson), with no continuity correction"
        h0 = "the row and column classifications are independent"
        h1 = "they are associated"
        method = (f"the chi-square distribution with (r - 1)(c - 1) = {df} degrees of freedom: an approximation to the "
                  f"statistic's exact distribution, held to its condition (every expected count at least {MIN_EXPECTED}, "
                  "checked); Pearson's X^2 with no continuity correction (Yates's is not applied); the tail correctly "
                  "rounded (Arb's incomplete gamma)")
        assumptions = [
            "each observation is independent and counted in exactly one cell",
            f"the chi-square approximation: every expected count at least {MIN_EXPECTED} (checked)",
            "no continuity correction: for a 2 x 2 table with small counts, fisher_exact is exact",
        ]
    guard.check_number(x2, "the statistic")
    places = E._places(node, [])
    p = E._outcome(RM.evaluate(RM.CHI2_SF, [RM.Ball(x2), RM.Ball(Fraction(df))], places, guard), U.PLAIN, node, [], places)
    reject = decide(p, RM.CHI2_SF, [x2, Fraction(df)], alpha_q.magnitude, guard)
    return finish(
        node, title=title, h0=h0, h1=h1,
        sidedness="the upper tail of X^2: any departure from H0, in any cell, raises it", alpha_q=alpha_q, n=n,
        statistic=("X2", E.Quantity(x2)), dof=E.Quantity(Fraction(df)), p=p, method=method, assumptions=assumptions,
        reject=reject, nodes=nodes,
    )


def binomial_weights(n: int, p: Fraction, guard: L.Guard) -> tuple[list[int], int]:
    """C(n, i) a^i (b - a)^(n - i) for p = a/b, and b^n: P(X = i) is the i-th over b^n. Sized first by b^n."""
    a, b = p.numerator, p.denominator
    exact_digits = RM.power_digits(b, n) if n else 1
    guard.check_digits(exact_digits or L.power_digits_at_least(b, n), f"probability's denominator ({b}^{n}, for p = {a}/{b})", exact_digits is not None)
    c = b - a
    out = []
    term = c**n
    for i in range(n + 1):
        if i % 64 == 63:
            guard.check_time()
        out.append(term)
        if i < n:
            term = term * (n - i) * a // ((i + 1) * c)
    return out, b**n


def binomial_p_value(k: int, n: int, w: list[int], total: int, alternative: str) -> Fraction:
    if alternative == "greater":
        return Fraction(sum(w[k:]), total)
    if alternative == "less":
        return Fraction(sum(w[: k + 1]), total)
    return Fraction(sum(x for x in w if x <= w[k]), total)


def _binomial(node: Any, args: list[Any], alpha_q: E.Quantity, guard: L.Guard, nodes: Any) -> E.Detailed:
    op, names = node.op, node.args
    k = whole(op, args[0], names[0], "k, the number of successes", 0)
    n = whole(op, args[1], names[1], "n, the number of trials", 1)
    if k > n:
        raise Refusal(f'{op}: k ("{names[0]}") is {k}, more than n ("{names[1]}") = {n}; k counts successes from 0 to n.', kind="out_of_domain")
    p0 = proportion(op, args[2], names[2], "p0, the success probability under H0")
    w, total = binomial_weights(n, p0, guard)
    p = binomial_p_value(k, n, w, total, node.alternative)
    guard.check_number(p)
    reject = p <= alpha_q.magnitude
    h1 = {"greater": "p > p0", "less": "p < p0", "two_sided": "p ≠ p0"}[node.alternative]
    method = {
        "greater": "exact: P(X >= k) under H0, summed in exact fractions",
        "less": "exact: P(X <= k) under H0, summed in exact fractions",
        "two_sided": "exact: the sum of P(X = i) under H0 over every i with P(X = i) <= P(X = k), in exact fractions "
                     "(R's binom.test method, its comparison exact rather than within a relative tolerance)",
    }[node.alternative]
    side = {"greater": "one-sided, upper tail", "less": "one-sided, lower tail",
            "two_sided": "two-sided: every outcome no more probable than the one observed"}[node.alternative]
    return finish(
        node, title="exact binomial test of a proportion", h0="p = p0: each trial succeeds with probability p0", h1=h1,
        sidedness=side, alpha_q=alpha_q, n=[n], statistic=("k", E.Quantity(Fraction(k))), dof=None, p=E.Quantity(p),
        method=method, reject=reject, nodes=nodes,
        assumptions=["the n trials are independent", "each has the same probability of success"],
    )


def fisher_weights(r1: int, r2: int, c1: int) -> dict[int, int]:
    """C(r1, x) C(r2, c1 - x) for every x the margins allow: P(X = x) is each over C(r1 + r2, c1)."""
    return {x: comb(r1, x) * comb(r2, c1 - x) for x in range(max(0, c1 - r2), min(r1, c1) + 1)}


def fisher_p_value(a: int, w: dict[int, int], total: int, alternative: str) -> Fraction:
    if alternative == "greater":
        return Fraction(sum(v for x, v in w.items() if x >= a), total)
    if alternative == "less":
        return Fraction(sum(v for x, v in w.items() if x <= a), total)
    return Fraction(sum(v for v in w.values() if v <= w[a]), total)


def _fisher(node: Any, args: list[Any], alpha_q: E.Quantity, guard: L.Guard, nodes: Any) -> E.Detailed:
    op, names = node.op, node.args
    value = args[0]
    if isinstance(value, A.Array) and value.data.ndim == 2 and value.shape != (2, 2):
        raise Refusal(f'{op} takes a 2 x 2 table, and "{names[0]}" is {A.shape_text(value.shape)}. For a larger table use chi2_independence.', kind="shape_mismatch")
    table = counts(op, value, names[0], 2, "a 2 x 2 table of counts")
    (a, b), (c, d) = table
    r1, r2, c1 = a + b, c + d, a + c
    total_n = r1 + r2
    if total_n == 0:
        raise Refusal(f'{op}: "{names[0]}" counts nothing.', kind="undefined")
    j = min(c1, total_n - c1)
    if j:
        guard.check_digits(L.power_digits_at_least(max(total_n // j, 1), j), "a binomial coefficient of the table's margins")
    w = fisher_weights(r1, r2, c1)
    p = fisher_p_value(a, w, comb(total_n, c1), node.alternative)
    guard.check_number(p)
    reject = p <= alpha_q.magnitude
    h1 = {"greater": "odds ratio > 1: row 1 more often in column 1 than row 2", "less": "odds ratio < 1",
          "two_sided": "odds ratio ≠ 1"}[node.alternative]
    method = {
        "greater": "exact: P(X >= a) for the top-left count X, hypergeometric given both margins, in exact fractions",
        "less": "exact: P(X <= a) for the top-left count X, hypergeometric given both margins, in exact fractions",
        "two_sided": "exact: the sum of every table's hypergeometric probability (given both margins) that is no more "
                     "than the observed table's, in exact fractions (R's fisher.test method, compared exactly)",
    }[node.alternative]
    side = {"greater": "one-sided, upper tail", "less": "one-sided, lower tail",
            "two_sided": "two-sided: every table no more probable than the one observed"}[node.alternative]
    return finish(
        node, title="Fisher's exact test of a 2 x 2 table", h0="odds ratio = 1: rows and columns are independent",
        h1=h1, sidedness=side, alpha_q=alpha_q, n=[r1, r2], statistic=("a", E.Quantity(Fraction(a))), dof=None,
        p=E.Quantity(p), method=method, reject=reject, nodes=nodes,
        assumptions=[
            "the observations are independent, each counted in one cell",
            "the test conditions on both margins; where the margins were not fixed by the design it is exact but "
            "conservative",
        ],
    )
