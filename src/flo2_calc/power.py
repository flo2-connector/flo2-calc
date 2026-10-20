"""Power and sample size, up front: for each named test, the power of a planned study at n, and the smallest
n whose power reaches a target, each a kept record.

req:calc-computes-power-and-sample-size-up-front (accepted 2026-10-19), option (e) of
dec:idea-how-a-statistical-hypothesis-test-is-designed-computed-and-read, in design 0bee0c00b35845f6, part of
req:the-math-of-a-study-is-designed-up-front; the choices in dec:v0-10-0-named-test-and-power-choices.

THE OPERATORS, two per named test (hypothesis.py), alpha always the last argument:

- z_test_power [delta, sigma, n, alpha], z_test_sample_size [delta, sigma, power, alpha]: delta the true
  difference from mu0 (signed: the alternative looks one way), sigma the known sd, in one dimension.
- t_test_one_sample_power and _sample_size: the same arguments, sigma the sd assumed for planning.
- t_test_two_sample_power and _sample_size: delta = mu1 - mu2, the common sd, n PER GROUP (two equal groups);
  "variance" must be "pooled": Welch's test has no exact power (its distribution under H1 depends on the
  unknown ratio of the variances), so its power is refused with that reason.
- chi2_goodness_of_fit_power [p0, p1, n, alpha] and _sample_size [p0, p1, power, alpha]: H0's proportions and
  the proportions the study expects, each summing to 1.
- chi2_independence_power [p1, n, alpha] and _sample_size [p1, power, alpha]: the joint proportions the study
  expects, a grid summing to 1; H0 is their margins' product.
- binomial_test_power [p0, p1, n, alpha] and _sample_size [p0, p1, power, alpha].
- fisher_exact_power [p1, p2, n, alpha] and _sample_size [p1, p2, power, alpha]: each group's success
  probability, n PER GROUP.

"alternative" (and "variance") as the test's own, never defaulted; the chi-square plans take none.

HOW EACH IS COMPUTED. The z-test's power is Phi(lambda - z) (and the far tail, two-sided), lambda = delta
sqrt(n) / sigma, from Arb's erfc and erfcinv: correctly rounded. The t-tests' is the noncentral t's tail beyond
the critical t (realmath.nct_cdf, Guenther's and Lenth's series with a rigorous bound on its remainder), the
critical t itself correctly rounded first and carried in as a ball: correctly rounded; both tails are counted
two-sided (R's power.t.test leaves the far one out unless strict = TRUE). The chi-square tests' is the
noncentral chi-square's tail beyond the critical X^2, lambda = n w^2 (Cohen's w^2 = sum (p1 - p0)^2 / p0):
correctly rounded, of that model, which is itself the standard APPROXIMATION to X^2 under H1, and the record says
so. The binomial and Fisher tests' powers are EXACT: the test's own rejection region at alpha, from its own exact
p-values (hypothesis.py), and the alternative's probability of it summed in exact fractions; the binomial's
record also holds the test's attained size, at most alpha.

A SAMPLE SIZE is the smallest n whose power reaches the target, each comparison DECIDED from enclosures (or
exactly). For the z, t and chi-square tests the power rises with n, so the search starts from the textbook
normal approximation and brackets the answer; for the exact tests the power is NOT monotone in n (it saw-teeths
as the rejection region jumps), so n is searched upward from the smallest, and the record says a larger n can
have less power. The step's detail shows the power at n and at n - 1. A planned chi-square test also needs every
expected count under H0 at least 5 (or the test would be refused): its sample size is the larger of the n the
power needs and the n the counts need, both shown. A target that no n reaches (at most alpha, 1 or more, no
effect, or an effect the other way from a one-sided alternative) is refused with its reason, never searched
for; a search past the host's deadline is stopped there like any calculation (limits.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable

from flo2_calc import arrays as A
from flo2_calc import evaluator as E
from flo2_calc import hypothesis as HT
from flo2_calc import limits as L
from flo2_calc import realmath as RM
from flo2_calc import units as U
from flo2_calc.errors import Refusal

# hypothesis.TESTS, written out here because this module is imported while hypothesis.py may still be loading
# (tests/test_power.py holds the two lists equal)
TESTS = ("z_test", "t_test_one_sample", "t_test_two_sample", "chi2_goodness_of_fit", "chi2_independence",
         "binomial_test", "fisher_exact")
PLANS: dict[str, str] = {f"{t}_{k}": t for t in TESTS for k in ("power", "sample_size")}
TITLES = {
    "z_test": "the z-test of one mean (sigma known)",
    "t_test_one_sample": "the one-sample t-test",
    "t_test_two_sample": "the pooled two-sample t-test (two equal groups)",
    "chi2_goodness_of_fit": "the chi-square goodness-of-fit test",
    "chi2_independence": "the chi-square test of independence",
    "binomial_test": "the exact binomial test",
    "fisher_exact": "Fisher's exact test (two equal groups)",
}


@dataclass
class Model:
    """One planned test: how its power at n is computed and decided against a target."""

    test: str
    n_min: int
    monotone: bool
    n_is: str
    effect: list[tuple[str, Any]]
    method: str
    assumptions: list[str]
    power_at: Callable[[int, int], tuple[E.Quantity, list[tuple[str, Any]]]]  # (n, places) -> (power, detail)
    reaches: Callable[[int, Fraction], bool]  # (n, target) -> power(n) >= target, decided
    start: Callable[[Fraction], int] | None = None  # a first guess at the n for a target (monotone models)
    n_counts: int = 1  # the least n whose expected counts under H0 are all at least 5 (chi-square)
    effect_sign: int | None = None  # the effect's direction (0: no effect), where the model has one


def apply(node: Any, args: list[Any], guard: L.Guard, nodes: dict[str, Any] | None = None) -> E.Detailed:
    op, names = node.op, node.args
    test = PLANS[op]
    sample_size = op.endswith("_sample_size")
    alpha_q = HT.alpha_of(op, args[-1], names[-1])
    a = alpha_q.magnitude
    places = E._places(node, [])
    model = _model(node, test, args[:-2], names[:-2], a, places, guard)
    given = args[-2]
    if sample_size:
        target = HT.proportion(op, given, names[-2], "the target power")
        _reachable(node, model, target, a, names[-2])
        n, found = _search(model, target, guard)
        power, more = model.power_at(n, places)
        detail = more + found + _with_n_minus_one(model, n, places)
        value: E.Quantity = E.Quantity(Fraction(n))
    else:
        n = HT.whole(op, given, names[-2], f"n, {model.n_is}", model.n_min)
        if test in HT.CHI2 and n < model.n_counts:
            raise Refusal(
                f"{op}: at n = {n} some expected count under H0 is below {HT.MIN_EXPECTED} (it needs n of at least "
                f"{model.n_counts}), so the planned chi-square test would be refused; plan a larger n.",
                kind="assumption_fails",
            )
        power, detail = model.power_at(n, places)
        value = power
    block: dict[str, Any] = {
        "test": test,
        "kind": "sample_size" if sample_size else "power",
        "title": f"{'the sample size for' if sample_size else 'the power of'} {TITLES[test]}",
        "alternative": node.alternative or "upper_tail",
        "alpha": _alpha_block(node, alpha_q, nodes),
        "effect": model.effect,
        "n": str(n),
        "n_is": model.n_is,
        "power": power,
        "method": model.method,
        "assumptions": model.assumptions,
    }
    if node.variance is not None:
        block["variance"] = node.variance
    if sample_size:
        block["target_power"] = E.Quantity(target)
    return E.Detailed(value, tuple(detail), ("test_plan", block))


def _alpha_block(node: Any, alpha_q: E.Quantity, nodes: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {"node": node.args[-1], **E.value_json(alpha_q)}
    src = HT._source_of(node, node.args[-1], nodes)
    if src is not None:
        out["source"] = src
    return out


def _reachable(node: Any, model: Model, target: Fraction, alpha: Fraction, name: str) -> None:
    op = node.op
    if target <= alpha:
        raise Refusal(
            f'{op}: the target power "{name}" is {E._number_text(target)}, at most alpha ({E._number_text(alpha)}); a test '
            "rejects a true H0 with probability alpha already, so a power worth planning for is above it.",
            kind="out_of_domain",
        )
    direction = model.effect_sign
    if direction == 0:
        raise Refusal(
            f"{op}: the effect is 0 (no effect): with no difference from H0 the power is alpha at every n, so no n "
            "reaches the target.",
            kind="out_of_domain",
        )
    if direction is not None and node.alternative in ("greater", "less") and direction != (1 if node.alternative == "greater" else -1):
        raise Refusal(
            f"{op}: the effect is in the direction the alternative \"{node.alternative}\" does not look, so the power falls "
            "below alpha as n grows and no n reaches the target. Check the effect's sign, or the alternative.",
            kind="out_of_domain",
        )


def _search(model: Model, target: Fraction, guard: L.Guard) -> tuple[int, list[tuple[str, Any]]]:
    """The smallest n >= n_min whose power reaches the target."""
    if model.monotone:
        lo = model.n_min - 1  # below every candidate: not known to reach
        if model.reaches(model.n_min, target):
            n = model.n_min
        else:
            lo = model.n_min
            hi = max(model.start(target) if model.start else model.n_min + 1, model.n_min + 1)
            while not model.reaches(hi, target):
                guard.check_time()
                lo, hi = hi, hi * 2
            while hi - lo > 1:  # lo does not reach, hi does
                guard.check_time()
                mid = (lo + hi) // 2
                if model.reaches(mid, target):
                    hi = mid
                else:
                    lo = mid
            n = hi
        detail: list[tuple[str, Any]] = []
        if model.n_counts > n:
            detail = [("n for the power", E.Quantity(Fraction(n))), ("n for the expected counts", E.Quantity(Fraction(model.n_counts)))]
            n = model.n_counts
        elif model.n_counts > 1:
            detail = [("n for the power", E.Quantity(Fraction(n))), ("n for the expected counts", E.Quantity(Fraction(model.n_counts)))]
        return n, detail
    n = model.n_min
    while not model.reaches(n, target):
        guard.check_time()
        n += 1
    return n, []


def _with_n_minus_one(model: Model, n: int, places: int) -> list[tuple[str, Any]]:
    """The power at n and at n - 1, which shows n is the smallest (for a monotone power)."""
    out = [("power at n", model.power_at(n, places)[0])]
    if n > model.n_min:
        out.append(("power at n - 1", model.power_at(n - 1, places)[0]))
    return out


# ---------------------------------------------------------------- the models


def _model(node: Any, test: str, args: list[Any], names: tuple[str, ...], a: Fraction, places: int, guard: L.Guard) -> Model:
    op = node.op
    if test in ("z_test", "t_test_one_sample", "t_test_two_sample"):
        if test == "t_test_two_sample" and node.variance != "pooled":
            raise Refusal(
                f"{op}: the power of Welch's test has no exact form (its distribution under H1 depends on the unknown "
                'ratio of the two variances), so flo2-calc does not compute one. Plan with "variance": "pooled" (equal '
                "variances), and say that this is the plan's assumption.",
                kind="out_of_domain",
            )
        delta = HT.one(op, args[0], names[0], "delta, the difference the study should find")
        sd = HT.one(op, args[1], names[1], "the sd")
        s = HT._in_unit(op, sd, delta.unit)
        if s <= 0:
            raise Refusal(f'{op}: the sd "{names[1]}" is {E.value_text(sd)}; it must be greater than 0.', kind="out_of_domain")
        ratio = delta.magnitude / s
        model = (_z if test == "z_test" else _t)(node, test, ratio, a, guard)
        model.effect = [("delta", delta), ("sd", sd), ("delta / sd", E.Quantity(ratio))]
        model.effect_sign = HT._sign(ratio)
        return model
    if test in HT.CHI2:
        return _chi2(node, test, args, names, a, guard)
    return _exact(node, test, args, names, a, guard)


def _z_of(q: Fraction, guard: L.Guard) -> float:
    """The standard normal quantile at q, to 6 digits: a search's first guess only."""
    return float(RM.evaluate(RM.NORMAL_QUANTILE, [RM.Ball(q), RM.Ball(Fraction(0)), RM.Ball(Fraction(1))], 6, guard).value)


def _normal_start(ratio: Fraction, a: Fraction, two_sided: bool, per: Fraction, guard: L.Guard) -> Callable[[Fraction], int]:
    """The textbook normal approximation n = per ((z_alpha + z_power) / ratio)^2: only a first guess."""

    def start(target: Fraction) -> int:
        za = _z_of(1 - (a / 2 if two_sided else a), guard)
        zb = _z_of(target, guard)
        return max(1, math.ceil(float(per) * ((za + zb) / abs(float(ratio))) ** 2))

    return start


def _z(node: Any, test: str, ratio: Fraction, a: Fraction, guard: L.Guard) -> Model:
    alt = node.alternative
    c2 = ratio * ratio
    sign = Fraction(HT._sign(ratio))
    fn = RM.z_power(alt)

    def power(n: int, places: int) -> tuple[E.Quantity, list[tuple[str, Any]]]:
        l2 = c2 * n
        guard.check_number(l2, "the noncentrality")
        return HT._rounded(fn, [l2, sign, a], node, U.PLAIN, places, guard), [("noncentrality^2", E.Quantity(l2))]

    def reaches(n: int, target: Fraction) -> bool:
        if c2 == 0:
            return a >= target
        return RM.compare_by(RM.fn_at(fn, [c2 * n, sign, a]), target, guard, "the power at n") > 0

    m = Model(test, 1, True, "the sample size", [],
              "the normal distribution of z under H1, mean lambda = delta sqrt(n) / sigma: the power Phi(lambda - z) (and the "
              "far tail, two-sided) from Arb's erfc and erfcinv, correctly rounded",
              ["the observations are independent", "sigma is known and is the sd given",
               "the sample mean is normally distributed (a judgement, not checked here)"],
              power, reaches, _normal_start(ratio, a, alt == "two_sided", Fraction(1), guard))
    return m


def _t(node: Any, test: str, ratio: Fraction, a: Fraction, guard: L.Guard) -> Model:
    alt = node.alternative
    two = test == "t_test_two_sample"
    c2 = ratio * ratio
    s = HT._sign(ratio)
    two_sided = alt == "two_sided"

    def parts(n: int) -> tuple[Fraction, Fraction]:
        """(lambda^2, nu) at n (per group for two samples)."""
        return (c2 * n / 2, Fraction(2 * n - 2)) if two else (c2 * n, Fraction(n - 1))

    def compute(n: int) -> Callable[[int], Callable[[], Any]]:
        l2, nu = parts(n)

        def at(working: int) -> Callable[[], Any]:
            tc = RM.t_critical(a, nu, two_sided, working + 5, guard)

            def run() -> Any:
                ball = RM.quantile_ball(tc, working + 5)
                lam = s * RM._arb(l2).sqrt()
                upper = 1 - RM.nct_cdf(ball, nu, lam, working, guard)  # P(T' > t_c)
                lower = 1 - RM.nct_cdf(ball, nu, -lam, working, guard)  # P(T' < -t_c)
                if alt == "greater":
                    return upper
                if alt == "less":
                    return lower
                return upper + lower

            return run

        return at

    def power(n: int, places: int) -> tuple[E.Quantity, list[tuple[str, Any]]]:
        l2, nu = parts(n)
        guard.check_number(l2, "the noncentrality")
        tc = RM.t_critical(a, nu, two_sided, places, guard)
        detail = [("dof", E.Quantity(nu)), ("noncentrality^2", E.Quantity(l2)),
                  ("critical t", E.Quantity(tc, U.PLAIN, E.Rounding(places, RM.half_unit(tc, places), True, (node.id,))))]
        if l2 == 0:
            return E.Quantity(a), detail
        c = RM.correctly_rounded_by(compute(n), places, guard, "the t-test's power")
        return E.Quantity(c, U.PLAIN, E.Rounding(places, RM.half_unit(c, places), True, (node.id,))), detail

    def reaches(n: int, target: Fraction) -> bool:
        if c2 == 0:
            return a >= target
        return RM.compare_by(compute(n), target, guard, "the power at n") > 0

    per = "per group (two equal groups)" if two else "the sample size"
    return Model(
        test, 2, True, per, [],
        "the noncentral t distribution of t under H1 (" + ("nu = 2n - 2, lambda = delta sqrt(n/2) / sd" if two else
        "nu = n - 1, lambda = delta sqrt(n) / sd") + "): its tail beyond the critical t, by Guenther's and Lenth's series "
        "with a rigorous bound on its remainder (Arb), the critical t correctly rounded first; correctly rounded. "
        "Two-sided, both tails are counted (R's power.t.test leaves the far one out unless strict = TRUE)",
        ["the observations are independent", "they come from a normal population with the sd given (an assumption of the plan)"]
        + (["the two groups are the same size and have equal variances (the pooled test)"] if two else []),
        power, reaches, _normal_start(ratio, a, two_sided, Fraction(2) if two else Fraction(1), guard),
    )


def _proportions(op: str, value: Any, name: str, ndim: int, positive: bool) -> list[Any]:
    """An exact plain array of proportions summing to exactly 1: each > 0 (positive) or >= 0."""
    if isinstance(value, bool) or not isinstance(value, A.Array) or value.data.ndim != ndim or value.kind != A.EXACT or value.unit != U.PLAIN:
        shape = "a 1-D array" if ndim == 1 else "a grid"
        raise Refusal(f'{op} takes "{name}" as {shape} of exact plain proportions, and it is not one.', kind="type_mismatch")
    flat = value.data.ravel().tolist()
    for i, x in enumerate(flat):
        if x < 0 or (positive and x == 0):
            raise Refusal(
                f'{op}: "{name}" holds {E._number_text(x)} at {A.index_text(i, value.shape)}; each proportion is '
                f"{'greater than 0' if positive else 'at least 0'}.",
                kind="out_of_domain",
            )
    total = sum(flat, Fraction(0))
    if total != 1:
        raise Refusal(f'{op}: the proportions "{name}" sum to {E._number_text(total)}, not 1. Give them exactly (1/3, not 0.33).', kind="out_of_domain")
    return value.data.tolist()


def _chi2(node: Any, test: str, args: list[Any], names: tuple[str, ...], a: Fraction, guard: L.Guard) -> Model:
    op = node.op
    if test == "chi2_goodness_of_fit":
        p0 = _proportions(op, args[0], names[0], 1, True)
        p1 = _proportions(op, args[1], names[1], 1, False)
        if len(p0) != len(p1):
            raise Refusal(f'{op}: "{names[0]}" has {len(p0)} categories and "{names[1]}" {len(p1)}.', kind="shape_mismatch")
        if len(p0) < 2:
            raise Refusal(f"{op}: a goodness-of-fit test needs at least 2 categories.", kind="undefined")
        w2 = sum(((x - y) ** 2 / y for x, y in zip(p1, p0)), Fraction(0))
        df = len(p0) - 1
        least = min(p0)
        effect: list[tuple[str, Any]] = [("w^2", E.Quantity(w2))]
    else:
        table = _proportions(op, args[0], names[0], 2, False)
        r, c = len(table), len(table[0])
        if r < 2 or c < 2:
            raise Refusal(f'{op}: a test of independence needs at least 2 rows and 2 columns; "{names[0]}" is {r} x {c}.', kind="shape_mismatch")
        rows = [sum(row, Fraction(0)) for row in table]
        cols = [sum((table[i][j] for i in range(r)), Fraction(0)) for j in range(c)]
        if 0 in rows or 0 in cols:
            raise Refusal(f'{op}: a row or column of "{names[0]}" has proportion 0, so its expected counts are 0.', kind="undefined")
        w2 = sum(((table[i][j] - rows[i] * cols[j]) ** 2 / (rows[i] * cols[j]) for i in range(r) for j in range(c)), Fraction(0))
        df = (r - 1) * (c - 1)
        least = min(rows) * min(cols)
        effect = [("w^2", E.Quantity(w2))]
    n_counts = max(1, math.ceil(HT.MIN_EXPECTED / least))

    def compute(n: int) -> Callable[[int], Callable[[], Any]]:
        lam = w2 * n

        def at(working: int) -> Callable[[], Any]:
            crit = RM.chi2_critical(a, df, working + 5, guard)
            return lambda: RM.ncx2_sf(RM.quantile_ball(crit, working + 5), df, RM._arb(lam), working, guard)

        return at

    def power(n: int, places: int) -> tuple[E.Quantity, list[tuple[str, Any]]]:
        lam = w2 * n
        guard.check_number(lam, "the noncentrality")
        crit = RM.chi2_critical(a, df, places, guard)
        detail = [("dof", E.Quantity(Fraction(df))), ("noncentrality", E.Quantity(lam)),
                  ("critical X2", E.Quantity(crit, U.PLAIN, E.Rounding(places, RM.half_unit(crit, places), True, (node.id,))))]
        if lam == 0:
            return E.Quantity(a), detail
        c = RM.correctly_rounded_by(compute(n), places, guard, "the chi-square test's power")
        return E.Quantity(c, U.PLAIN, E.Rounding(places, RM.half_unit(c, places), True, (node.id,))), detail

    def reaches(n: int, target: Fraction) -> bool:
        if w2 == 0:
            return a >= target
        return RM.compare_by(compute(n), target, guard, "the power at n") > 0

    def start(target: Fraction) -> int:
        # Cohen's normal approximation for one degree of freedom, then grown with the degrees of freedom
        za, zb = _z_of(1 - a / 2, guard), _z_of(target, guard)
        return max(1, math.ceil((za + zb) ** 2 * (1 + 0.5 * (df - 1)) / float(w2)))

    m = Model(
        test, 1, True, "observations in all", effect,
        f"the noncentral chi-square distribution with {df} degrees of freedom and lambda = n w^2 (Cohen's w^2 = "
        + ("sum (p1 - p0)^2 / p0" if test == "chi2_goodness_of_fit" else "sum (p_ij - p_i. p_.j)^2 / (p_i. p_.j)")
        + "): the standard approximation to X^2 under H1 (Cohen 1988); its tail beyond the critical X^2 as a Poisson "
          "mixture of incomplete gammas with a rigorous bound on its remainder (Arb), correctly rounded for that model",
        ["each observation is independent and counted once",
         f"every expected count under H0 is at least {HT.MIN_EXPECTED} at the planned n (checked), so the test can be computed",
         "the proportions under H1 are the study's assumption"],
        power, reaches, start, n_counts,
    )
    m.effect_sign = 1 if w2 else 0
    return m


def _exact(node: Any, test: str, args: list[Any], names: tuple[str, ...], a: Fraction, guard: L.Guard) -> Model:
    op, alt = node.op, node.alternative
    if test == "binomial_test":
        p0 = HT.proportion(op, args[0], names[0], "p0, the success probability under H0")
        p1 = HT.proportion(op, args[1], names[1], "p1, the success probability the study expects", open_=False)
        effect: list[tuple[str, Any]] = [("p0", E.Quantity(p0)), ("p1", E.Quantity(p1))]
        diff = p1 - p0

        def power(n: int, places: int) -> tuple[E.Quantity, list[tuple[str, Any]]]:
            w0, t0 = HT.binomial_weights(n, p0, guard)
            reg = region_of(dict(enumerate(w0)), t0, a, alt)
            w1, t1 = HT.binomial_weights(n, p1, guard)
            w = Fraction(sum(w1[x] for x in reg), t1)
            guard.check_number(w)
            return E.Quantity(w), [("size", E.Quantity(Fraction(sum(w0[x] for x in reg), t0)))]

        title_n = "the number of trials"
        method = ("exact: the binomial test's own rejection region at alpha (every k whose exact p-value is at most "
                  "alpha), and P(X in it) under p1, summed in exact fractions; the size, P(X in it) under p0, is at most "
                  "alpha")
    else:
        p1 = HT.proportion(op, args[0], names[0], "p1, group 1's success probability", open_=False)
        p2 = HT.proportion(op, args[1], names[1], "p2, group 2's success probability", open_=False)
        effect = [("p1", E.Quantity(p1)), ("p2", E.Quantity(p2))]
        diff = p1 - p2

        def power(n: int, places: int) -> tuple[E.Quantity, list[tuple[str, Any]]]:
            w1, t1 = HT.binomial_weights(n, p1, guard)
            w2, t2 = HT.binomial_weights(n, p2, guard)
            hits = 0
            for m in range(2 * n + 1):
                guard.check_time()
                hw = HT.fisher_weights(n, n, m)
                total = math.comb(2 * n, m)
                for x in region_of(hw, total, a, alt):
                    hits += w1[x] * w2[m - x]
            w = Fraction(hits, t1 * t2)
            guard.check_number(w)
            return E.Quantity(w), []

        title_n = "per group (two equal groups)"
        method = ("exact: for every total of successes, Fisher's own rejection region at alpha (every table whose exact "
                  "p-value given both margins is at most alpha), and the probability of those tables when group 1 succeeds "
                  "with p1 and group 2 with p2, summed in exact fractions")

    def reaches(n: int, target: Fraction) -> bool:
        return Fraction(power(n, 1)[0].magnitude) >= target

    m = Model(
        test, 1, False, title_n, effect, method,
        ["the trials are independent, each with the probability given"]
        + ([] if test == "binomial_test" else ["the two groups are the same size"])
        + ["the power of an exact test is not monotone in n: it saw-teeths as the rejection region jumps, so a larger n "
           "can have less power; a sample size here is the smallest n that reaches the target"],
        power, reaches,
    )
    m.effect_sign = HT._sign(diff)
    return m


def region_of(weights: dict[int, int], total: int, a: Fraction, alt: str) -> list[int]:
    """The outcomes x a test rejects at alpha: those whose exact p-value is at most alpha, where outcome x has
    probability weights[x] / total under H0. "greater" sums from the top, "less" from the bottom, and two-sided
    sums every weight no more than x's own (hypothesis.binomial_p_value and fisher_p_value, for every x at once)."""
    xs = sorted(weights)
    bound = a * total  # p <= alpha  <=>  the summed weights <= alpha * total
    if alt in ("greater", "less"):
        out, acc = [], 0
        for x in (reversed(xs) if alt == "greater" else xs):
            acc += weights[x]
            if acc <= bound:
                out.append(x)
            else:
                break
        return out
    tally: dict[int, int] = {}
    for v in weights.values():
        tally[v] = tally.get(v, 0) + v
    below: dict[int, int] = {}
    acc = 0
    for v in sorted(tally):
        acc += tally[v]
        below[v] = acc
    return [x for x in xs if below[weights[x]] <= bound]
