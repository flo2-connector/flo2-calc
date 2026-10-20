"""Power and sample size, up front: for each named test, the power of a planned study at n, and the
smallest n that reaches a target power, each a kept record.

req:calc-computes-power-and-sample-size-up-front in design 0bee0c00b35845f6 (flo2-calc 0.10.0, option
(e) of dec:idea-how-a-statistical-hypothesis-test-is-designed-computed-and-read). Pinned as a CLASS:
every power and sample-size record carries the same fields; the alternative is never defaulted; a
sample size is the smallest n whose power reaches the target, shown by the power at n and at n - 1.

Reference values, and where each comes from:
- PUBLISHED: R's power.t.test examples (two-sample, sd 1, alpha 0.05): n = 20, delta = 1 gives power
  0.8689528 (R leaves out the far tail, strict = FALSE; flo2-calc counts both tails, so it agrees to
  3e-7); power 0.90 needs n = 22.02110 per group (23 whole), and one-sided n = 17.84713 (18). Cohen's
  chi-square: w = 0.3, df = 1, alpha 0.05, power 0.80 needs N = 87.2 (88 whole).
- AN IDENTITY: a chi-square test of one degree of freedom IS a two-sided z-test (chi-square_1 is Z^2), so
  its power at n equals the z-test's at delta / sigma = w to every digit: two routes through Arb (the
  noncentral chi-square's Poisson mixture of incomplete gammas, and erfc) that must agree exactly.
- INDEPENDENT COMPUTATION (mpmath, not Arb): the normal power from mpmath's ncdf; the noncentral t by
  integrating its definition over the chi-square density; the noncentral chi-square by integrating its
  Bessel-function density. The exact tests (binomial, Fisher) by an enumeration written here in exact
  fractions: every outcome's own p-value, the rejection region, and the alternative's probability of it.
"""

from __future__ import annotations

import json
from fractions import Fraction
from math import comb
from typing import Any

import jsonschema
import mpmath as mp
import pytest
from conftest import graph, inp, op
from oracle import mpq, rounded

from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph
from flo2_calc.numbers import parse_number

PLAN_FIELDS = {"test", "kind", "title", "alternative", "alpha", "effect", "n", "power", "method", "assumptions"}


def run(*nodes: dict, result: Any = None, limits: L.Limits = L.LAPTOP) -> dict:
    return evaluation_json(evaluate(read_graph(graph(*nodes, result=result)), L.Guard(limits)))


def entry(answer: dict, node: str = "w") -> dict:
    assert answer["status"] == "ok", answer.get("refused")
    return next(v for v in answer["values"] if v["node"] == node)


def plan(answer: dict, node: str = "w") -> dict:
    return entry(answer, node)["test_plan"]


def value_of(v: dict) -> Fraction:
    return parse_number((v.get("exact") or v["value"]).split(" ")[0])


def alpha(a: str = "0.05") -> dict:
    return inp("alpha", a, {"design_node": "con:significance-level"})


# ---------------------------------------------------------------- independent oracles (mpmath)


def z_quantile(p: mp.mpf) -> mp.mpf:
    return mp.sqrt(2) * mp.erfinv(2 * p - 1)


def z_power(lam: mp.mpf, a: Fraction, alt: str) -> mp.mpf:
    al = mpq(a)
    if alt == "greater":
        return mp.ncdf(lam - z_quantile(1 - al))
    if alt == "less":
        return mp.ncdf(-lam - z_quantile(1 - al))
    c = z_quantile(1 - al / 2)
    return mp.ncdf(lam - c) + mp.ncdf(-lam - c)


def t_cdf(t: mp.mpf, nu: int) -> mp.mpf:
    x = nu / (nu + t * t)
    tail = mp.betainc(mp.mpf(nu) / 2, mp.mpf(1) / 2, 0, x, regularized=True) / 2
    return 1 - tail if t > 0 else tail


def t_quantile(p: mp.mpf, nu: int) -> mp.mpf:
    return mp.findroot(lambda t: t_cdf(t, nu) - p, z_quantile(p))


def nct_cdf(t: mp.mpf, nu: int, lam: mp.mpf) -> mp.mpf:
    """P(T' <= t) for T' = (Z + lam) / sqrt(V / nu): the integral of Phi(t sqrt(v / nu) - lam) over V's chi-square density."""
    k = mp.mpf(nu) / 2
    dens = lambda v: v ** (k - 1) * mp.exp(-v / 2) / (2**k * mp.gamma(k))  # noqa: E731
    return mp.quad(lambda v: mp.ncdf(t * mp.sqrt(v / nu) - lam) * dens(v), [0, nu, 4 * nu + 40, mp.inf])


def t_power(lam: mp.mpf, nu: int, a: Fraction, alt: str) -> mp.mpf:
    al = mpq(a)
    if alt == "greater":
        return 1 - nct_cdf(t_quantile(1 - al, nu), nu, lam)
    if alt == "less":
        return nct_cdf(-t_quantile(1 - al, nu), nu, lam)
    c = t_quantile(1 - al / 2, nu)
    return 1 - nct_cdf(c, nu, lam) + nct_cdf(-c, nu, lam)


def chi2_quantile(p: mp.mpf, df: int) -> mp.mpf:
    return mp.findroot(lambda x: mp.gammainc(mp.mpf(df) / 2, 0, x / 2, regularized=True) - p, df + 2)


def ncx2_sf(c: mp.mpf, df: int, lam: mp.mpf) -> mp.mpf:
    """P(X > c) by integrating the noncentral chi-square's Bessel-function density."""
    k = mp.mpf(df)
    dens = lambda x: mp.exp(-(x + lam) / 2) / 2 * (x / lam) ** (k / 4 - mp.mpf(1) / 2) * mp.besseli(k / 2 - 1, mp.sqrt(lam * x))  # noqa: E731
    return mp.quad(dens, [c, c + 2 * (df + lam) + 50, mp.inf])


def binomial_p_values(n: int, p0: Fraction, alt: str) -> list[Fraction]:
    f = [Fraction(comb(n, i)) * p0**i * (1 - p0) ** (n - i) for i in range(n + 1)]
    if alt == "greater":
        return [sum(f[i:], Fraction(0)) for i in range(n + 1)]
    if alt == "less":
        return [sum(f[: i + 1], Fraction(0)) for i in range(n + 1)]
    return [sum((v for v in f if v <= f[i]), Fraction(0)) for i in range(n + 1)]


def binomial_power(p0: Fraction, p1: Fraction, n: int, a: Fraction, alt: str) -> tuple[Fraction, Fraction]:
    pv = binomial_p_values(n, p0, alt)
    region = [i for i in range(n + 1) if pv[i] <= a]
    power = sum((Fraction(comb(n, i)) * p1**i * (1 - p1) ** (n - i) for i in region), Fraction(0))
    size = sum((Fraction(comb(n, i)) * p0**i * (1 - p0) ** (n - i) for i in region), Fraction(0))
    return power, size


def fisher_p(a: int, b: int, n: int, alt: str) -> Fraction:
    """Fisher's p for the table [[a, n - a], [b, n - b]], rows the two groups, columns success and failure."""
    m = a + b
    h = {x: Fraction(comb(n, x) * comb(n, m - x), comb(2 * n, m)) for x in range(max(0, m - n), min(n, m) + 1)}
    if alt == "greater":
        return sum((v for x, v in h.items() if x >= a), Fraction(0))
    if alt == "less":
        return sum((v for x, v in h.items() if x <= a), Fraction(0))
    return sum((v for v in h.values() if v <= h[a]), Fraction(0))


def fisher_power(p1: Fraction, p2: Fraction, n: int, al: Fraction, alt: str) -> Fraction:
    total = Fraction(0)
    for a in range(n + 1):
        for b in range(n + 1):
            if fisher_p(a, b, n, alt) <= al:
                total += Fraction(comb(n, a)) * p1**a * (1 - p1) ** (n - a) * Fraction(comb(n, b)) * p2**b * (1 - p2) ** (n - b)
    return total


# ---------------------------------------------------------------- the z-test


@pytest.mark.parametrize("alt", ["greater", "less", "two_sided"])
def test_z_power_matches_the_normal_closed_form(alt):
    ans = run(inp("d", "0.5 mm", "smallest difference worth finding"), inp("s", "1.2 mm", "process sd"), inp("n", "30"),
              alpha(), op("w", "z_test_power", "d", "s", "n", "alpha", alternative=alt))
    p = plan(ans)
    with mp.workdps(120):
        expected = rounded(z_power(mp.sqrt(mpq(Fraction(1, 4) * 30 / Fraction(36, 25))), Fraction(1, 20), alt))
    assert value_of(p["power"]) == expected and p["power"]["rounded"]["correctly_rounded"] is True
    assert p["kind"] == "power" and p["n"] == "30" and p["alternative"] == alt


def test_z_power_with_no_effect_is_alpha_exactly():
    ans = run(inp("d", "0 mm"), inp("s", "1 mm"), inp("n", "30"), alpha(),
              op("w", "z_test_power", "d", "s", "n", "alpha", alternative="two_sided"))
    assert entry(ans)["value"] == "0.05" and "rounded" not in entry(ans)


def test_z_sample_size_is_the_smallest_n_that_reaches_the_power():
    ans = run(inp("d", "0.5 mm"), inp("s", "1 mm"), inp("target", "0.8"), alpha(),
              op("w", "z_test_sample_size", "d", "s", "target", "alpha", alternative="two_sided"))
    p = plan(ans)
    assert entry(ans)["value"] == "32" and p["n"] == "32" and p["kind"] == "sample_size"  # (1.96 + 0.8416)^2 / 0.25 = 31.4
    with mp.workdps(60):
        assert z_power(mp.sqrt(mp.mpf(32) / 4), Fraction(1, 20), "two_sided") >= mp.mpf("0.8")
        assert z_power(mp.sqrt(mp.mpf(31) / 4), Fraction(1, 20), "two_sided") < mp.mpf("0.8")
    shown = {d["name"]: d for d in entry(ans)["detail"]}
    assert value_of(shown["power at n"]) >= Fraction(8, 10) > value_of(shown["power at n - 1"])
    assert value_of(p["target_power"]) == Fraction(8, 10)


# ---------------------------------------------------------------- the t-tests


def test_two_sample_t_power_matches_r_and_the_integral():
    ans = run(inp("d", "1 mm"), inp("s", "1 mm"), inp("n", "20", "per group"), alpha(),
              op("w", "t_test_two_sample_power", "d", "s", "n", "alpha", alternative="two_sided", variance="pooled"))
    w = value_of(plan(ans)["power"])
    assert abs(w - Fraction("0.8689528")) < Fraction(3, 10**7)  # R: power.t.test(n = 20, delta = 1)
    with mp.workdps(40):
        assert abs(mpq(w) - t_power(mp.sqrt(mp.mpf(10)), 38, Fraction(1, 20), "two_sided")) < mp.mpf(10) ** -20
    assert plan(ans)["power"]["rounded"]["correctly_rounded"] is True
    assert plan(ans)["variance"] == "pooled" and "per group" in plan(ans)["n_is"]


@pytest.mark.parametrize("alt, n", [("two_sided", "23"), ("greater", "18")])
def test_two_sample_t_sample_size_matches_r(alt, n):
    ans = run(inp("d", "1 mm"), inp("s", "1 mm"), inp("target", "0.9"), alpha(),
              op("w", "t_test_two_sample_sample_size", "d", "s", "target", "alpha", alternative=alt, variance="pooled"))
    assert entry(ans)["value"] == n  # R: 22.02110 two-sided, 17.84713 one-sided, per group


@pytest.mark.parametrize("alt, d", [("greater", "0.6"), ("less", "-0.6"), ("two_sided", "0.6"), ("greater", "-0.2")])
def test_one_sample_t_power_matches_the_integral(alt, d):
    ans = run(inp("d", f"{d} V"), inp("s", "1 V"), inp("n", "15"), alpha(),
              op("w", "t_test_one_sample_power", "d", "s", "n", "alpha", alternative=alt))
    w = value_of(plan(ans)["power"])
    with mp.workdps(40):
        lam = mpq(parse_number(d)) * mp.sqrt(15)
        assert abs(mpq(w) - t_power(lam, 14, Fraction(1, 20), alt)) < mp.mpf(10) ** -20


def test_the_power_of_welchs_test_is_refused_with_its_reason():
    ans = run(inp("d", "1 mm"), inp("s", "1 mm"), inp("n", "20"), alpha(),
              op("w", "t_test_two_sample_power", "d", "s", "n", "alpha", alternative="two_sided", variance="welch"))
    assert ans["status"] == "refused" and "pooled" in ans["refused"]["reason"]


# ---------------------------------------------------------------- the chi-square tests


def test_a_one_degree_chi_square_power_is_the_two_sided_z_power_to_every_digit():
    w2 = Fraction(9, 100)  # w = 0.3 through p0 = (1/2, 1/2), p1 = (0.65, 0.35)
    chi = run(inp("p0", {"array": ["1/2", "1/2"]}, "H0"), inp("p1", {"array": ["0.65", "0.35"]}, "H1"), inp("n", "88"), alpha(),
              op("w", "chi2_goodness_of_fit_power", "p0", "p1", "n", "alpha"))
    z = run(inp("d", "0.3"), inp("s", "1"), inp("n", "88"), alpha(), op("w", "z_test_power", "d", "s", "n", "alpha", alternative="two_sided"))
    assert plan(chi)["power"] == plan(z)["power"]
    assert any(e["name"] == "w^2" and value_of(e) == w2 for e in plan(chi)["effect"])
    ss = run(inp("p0", {"array": ["1/2", "1/2"]}, "H0"), inp("p1", {"array": ["0.65", "0.35"]}, "H1"), inp("t", "0.8"), alpha(),
             op("w", "chi2_goodness_of_fit_sample_size", "p0", "p1", "t", "alpha"))
    assert entry(ss)["value"] == "88"  # Cohen: N = 87.2


def test_chi_square_power_matches_the_noncentral_density():
    ans = run(inp("p0", {"array": ["1/4", "1/4", "1/4", "1/4"]}), inp("p1", {"array": ["0.3", "0.3", "0.2", "0.2"]}),
              inp("n", "200"), alpha(), op("w", "chi2_goodness_of_fit_power", "p0", "p1", "n", "alpha"))
    w = value_of(plan(ans)["power"])
    lam = 200 * sum(((a - b) ** 2 / b for a, b in zip(map(Fraction, ("0.3", "0.3", "0.2", "0.2")), [Fraction(1, 4)] * 4)), Fraction(0))
    with mp.workdps(40):
        assert abs(mpq(w) - ncx2_sf(chi2_quantile(mp.mpf("0.95"), 3), 3, mpq(lam))) < mp.mpf(10) ** -20
    assert "approximation" in plan(ans)["method"]


def test_chi_square_independence_power_and_sample_size():
    table = {"array": [["0.2", "0.1"], ["0.3", "0.4"]]}
    ans = run(inp("p1", table, "H1 joint proportions"), inp("n", "150"), alpha(), op("w", "chi2_independence_power", "p1", "n", "alpha"))
    rows, cols = [Fraction(3, 10), Fraction(7, 10)], [Fraction(1, 2), Fraction(1, 2)]
    cells = [[Fraction("0.2"), Fraction("0.1")], [Fraction("0.3"), Fraction("0.4")]]
    w2 = sum(((cells[i][j] - rows[i] * cols[j]) ** 2 / (rows[i] * cols[j]) for i in range(2) for j in range(2)), Fraction(0))
    with mp.workdps(40):
        expected = ncx2_sf(chi2_quantile(mp.mpf("0.95"), 1), 1, mpq(150 * w2))
        assert abs(mpq(value_of(plan(ans)["power"])) - expected) < mp.mpf(10) ** -20
    ss = run(inp("p1", table), inp("t", "0.8"), alpha(), op("w", "chi2_independence_sample_size", "p1", "t", "alpha"))
    n = int(entry(ss)["value"])
    with mp.workdps(40):
        assert ncx2_sf(chi2_quantile(mp.mpf("0.95"), 1), 1, mpq(n * w2)) >= mp.mpf("0.8")
        assert ncx2_sf(chi2_quantile(mp.mpf("0.95"), 1), 1, mpq((n - 1) * w2)) < mp.mpf("0.8")


def test_a_planned_chi_square_whose_expected_counts_fall_below_5_is_planned_larger():
    ans = run(inp("p0", {"array": ["0.9", "0.1"]}), inp("p1", {"array": ["0.5", "0.5"]}), inp("t", "0.8"), alpha(),
              op("w", "chi2_goodness_of_fit_sample_size", "p0", "p1", "t", "alpha"))
    # the power alone needs very few, but at n < 50 the H0 expected count n * 0.1 is below 5: the test would be refused
    assert entry(ans)["value"] == "50"
    shown = {d["name"]: d["value"] for d in entry(ans)["detail"]}
    assert shown["n for the expected counts"] == "50" and int(shown["n for the power"]) < 50
    refused = run(inp("p0", {"array": ["0.9", "0.1"]}), inp("p1", {"array": ["0.5", "0.5"]}), inp("n", "20"), alpha(),
                  op("w", "chi2_goodness_of_fit_power", "p0", "p1", "n", "alpha"))
    assert refused["refused"]["kind"] == "assumption_fails"


# ---------------------------------------------------------------- the exact tests


@pytest.mark.parametrize("alt, p1", [("greater", "0.7"), ("less", "0.3"), ("two_sided", "0.7")])
def test_binomial_power_is_exact_and_matches_an_enumeration(alt, p1):
    ans = run(inp("p0", "1/2"), inp("p1", p1), inp("n", "30"), alpha(),
              op("w", "binomial_test_power", "p0", "p1", "n", "alpha", alternative=alt))
    power, size = binomial_power(Fraction(1, 2), Fraction(p1), 30, Fraction(1, 20), alt)
    assert value_of(plan(ans)["power"]) == power and "rounded" not in plan(ans)["power"]
    shown = {d["name"]: d for d in entry(ans)["detail"]}
    assert value_of(shown["size"]) == size <= Fraction(1, 20)
    assert plan(ans)["method"].startswith("exact")


def test_binomial_sample_size_is_the_smallest_n_and_says_power_is_not_monotone():
    ans = run(inp("p0", "1/2"), inp("p1", "0.75"), inp("t", "0.8"), alpha(),
              op("w", "binomial_test_sample_size", "p0", "p1", "t", "alpha", alternative="greater"))
    n = int(entry(ans)["value"])
    powers = [binomial_power(Fraction(1, 2), Fraction(3, 4), k, Fraction(1, 20), "greater")[0] for k in range(1, n + 1)]
    assert powers[-1] >= Fraction(4, 5) and all(w < Fraction(4, 5) for w in powers[:-1])
    assert any("not monotone" in a or "saw" in a for a in plan(ans)["assumptions"] + [plan(ans)["method"]])


@pytest.mark.parametrize("alt", ["greater", "two_sided"])
def test_fisher_power_is_exact_and_matches_an_enumeration(alt):
    ans = run(inp("p1", "0.8"), inp("p2", "0.3"), inp("n", "12", "per group"), alpha(),
              op("w", "fisher_exact_power", "p1", "p2", "n", "alpha", alternative=alt))
    assert value_of(plan(ans)["power"]) == fisher_power(Fraction(4, 5), Fraction(3, 10), 12, Fraction(1, 20), alt)


def test_fisher_sample_size_is_the_smallest_n_per_group():
    ans = run(inp("p1", "0.9"), inp("p2", "0.3"), inp("t", "0.8"), alpha(),
              op("w", "fisher_exact_sample_size", "p1", "p2", "t", "alpha", alternative="two_sided"))
    n = int(entry(ans)["value"])
    ws = [fisher_power(Fraction(9, 10), Fraction(3, 10), k, Fraction(1, 20), "two_sided") for k in range(1, n + 1)]
    assert ws[-1] >= Fraction(4, 5) and all(w < Fraction(4, 5) for w in ws[:-1])


# ---------------------------------------------------------------- the class: same fields, nothing defaulted

E = [inp("d", "0.5 mm"), inp("s", "1 mm"), alpha()]
PLANS = [
    ("z_test_power", E + [inp("n", "20")], ["d", "s", "n", "alpha"], {"alternative": "greater"}),
    ("z_test_sample_size", E + [inp("t", "0.8")], ["d", "s", "t", "alpha"], {"alternative": "greater"}),
    ("t_test_one_sample_power", E + [inp("n", "20")], ["d", "s", "n", "alpha"], {"alternative": "two_sided"}),
    ("t_test_one_sample_sample_size", E + [inp("t", "0.8")], ["d", "s", "t", "alpha"], {"alternative": "two_sided"}),
    ("t_test_two_sample_power", E + [inp("n", "20")], ["d", "s", "n", "alpha"], {"alternative": "two_sided", "variance": "pooled"}),
    ("t_test_two_sample_sample_size", E + [inp("t", "0.8")], ["d", "s", "t", "alpha"], {"alternative": "two_sided", "variance": "pooled"}),
    ("chi2_goodness_of_fit_power", [inp("p0", {"array": ["1/2", "1/2"]}), inp("p1", {"array": ["0.6", "0.4"]}), inp("n", "200"), alpha()], ["p0", "p1", "n", "alpha"], {}),
    ("chi2_goodness_of_fit_sample_size", [inp("p0", {"array": ["1/2", "1/2"]}), inp("p1", {"array": ["0.6", "0.4"]}), inp("t", "0.8"), alpha()], ["p0", "p1", "t", "alpha"], {}),
    ("chi2_independence_power", [inp("p1", {"array": [["0.3", "0.2"], ["0.2", "0.3"]]}), inp("n", "100"), alpha()], ["p1", "n", "alpha"], {}),
    ("chi2_independence_sample_size", [inp("p1", {"array": [["0.3", "0.2"], ["0.2", "0.3"]]}), inp("t", "0.8"), alpha()], ["p1", "t", "alpha"], {}),
    ("binomial_test_power", [inp("p0", "1/2"), inp("p1", "0.7"), inp("n", "40"), alpha()], ["p0", "p1", "n", "alpha"], {"alternative": "greater"}),
    ("binomial_test_sample_size", [inp("p0", "1/2"), inp("p1", "0.7"), inp("t", "0.8"), alpha()], ["p0", "p1", "t", "alpha"], {"alternative": "greater"}),
    ("fisher_exact_power", [inp("p1", "0.8"), inp("p2", "0.3"), inp("n", "10"), alpha()], ["p1", "p2", "n", "alpha"], {"alternative": "two_sided"}),
    ("fisher_exact_sample_size", [inp("p1", "0.9"), inp("p2", "0.2"), inp("t", "0.8"), alpha()], ["p1", "p2", "t", "alpha"], {"alternative": "greater"}),
]


@pytest.mark.parametrize("name, nodes, args, fields", PLANS, ids=[p[0] for p in PLANS])
def test_every_power_and_sample_size_keeps_the_same_fields(name, nodes, args, fields):
    ans = run(*nodes, op("w", name, *args, **fields))
    p = plan(ans)
    assert PLAN_FIELDS <= set(p), PLAN_FIELDS - set(p)
    assert set(p) - PLAN_FIELDS <= {"variance", "target_power", "n_is", "dof"}, set(p) - PLAN_FIELDS
    assert p["test"] == name.rsplit("_power", 1)[0].rsplit("_sample_size", 1)[0]
    assert p["kind"] == ("sample_size" if name.endswith("_sample_size") else "power")
    assert ("target_power" in p) == (p["kind"] == "sample_size")
    assert p["alpha"]["value"] == "0.05" and p["alpha"]["source"] == {"design_node": "con:significance-level"}
    assert p["effect"] and all("name" in e and "value" in e for e in p["effect"])
    assert p["assumptions"] and p["method"]
    if p["kind"] == "sample_size":
        assert entry(ans)["value"] == p["n"]
        shown = {d["name"] for d in entry(ans)["detail"]}
        assert {"power at n", "power at n - 1"} <= shown or p["n"] in ("1", "2")
    else:
        assert entry(ans)["value"] == p["power"]["value"]


@pytest.mark.parametrize("name, nodes, args, fields", [p for p in PLANS if p[3].get("alternative")],
                         ids=[p[0] for p in PLANS if p[3].get("alternative")])
def test_a_plans_alternative_is_never_defaulted(name, nodes, args, fields):
    with pytest.raises(CallError, match='needs "alternative"'):
        read_graph(graph(*nodes, op("w", name, *args, **{k: v for k, v in fields.items() if k != "alternative"})))


def test_a_target_that_cannot_be_reached_is_refused_not_searched_for_ever():
    cases = [
        (op("w", "z_test_sample_size", "d0", "s", "t", "alpha", alternative="two_sided"), "no effect"),
        (op("w", "z_test_sample_size", "dn", "s", "t", "alpha", alternative="greater"), "direction"),
        (op("w", "z_test_sample_size", "d", "s", "one", "alpha", alternative="greater"), "power"),
        (op("w", "t_test_one_sample_sample_size", "d", "s", "small", "alpha", alternative="greater"), "alpha"),
    ]
    for node, word in cases:
        ans = run(inp("d", "0.5 mm"), inp("d0", "0 mm"), inp("dn", "-0.5 mm"), inp("s", "1 mm"), inp("t", "0.8"),
                  inp("one", "1"), inp("small", "0.01"), alpha(), node)
        assert ans["status"] == "refused" and word in ans["refused"]["reason"], (word, ans["refused"])


def test_a_sample_size_search_past_the_deadline_stops_and_a_larger_host_completes_it():
    g = graph(inp("p1", "0.52", "H1"), inp("p2", "0.5", "H0 rate"), inp("t", "0.9", "target"), alpha(),
              op("w", "fisher_exact_sample_size", "p1", "p2", "t", "alpha", alternative="greater"))
    ev = evaluate(read_graph(g), L.Guard(L.Limits(deadline_ms=200)))
    assert not ev.ok and ev.refusal["kind"] == "exceeds_limits" and ev.refusal["limit"]["name"] == "deadline"
    pending = R.build_pending(read_graph(g), "fisher-plan", None, ev.refusal, L.Limits(deadline_ms=200))
    jsonschema.Draft202012Validator(R.schema()).validate(pending)
    assert pending["status"] == "not_computed"


def test_a_plan_is_kept_as_a_record_that_re_runs():
    g = graph(inp("d", "1 mm", {"design_node": "con:smallest-effect-worth-finding"}), inp("s", "1 mm", "pilot study sd"),
              inp("t", "0.9", {"design_node": "con:target-power"}), alpha(),
              op("n", "t_test_two_sample_sample_size", "d", "s", "t", "alpha", alternative="two_sided", variance="pooled"),
              op("w", "t_test_two_sample_power", "d", "s", "n", "alpha", alternative="two_sided", variance="pooled"),
              result=["n", "w"])
    rec = R.build(evaluate(read_graph(g)), "sleep-study-plan", {"design_node": "req:h1-drug-2-adds-sleep"})
    jsonschema.Draft202012Validator(R.schema()).validate(rec)
    kept = {v["node"]: v for v in rec["values"]}
    assert kept["n"]["value"] == "23" and kept["n"]["test_plan"]["kind"] == "sample_size"
    assert value_of(kept["w"]["test_plan"]["power"]) >= Fraction(9, 10)
    assert R.rerun(R.load(rec))["reproduces"] is True
    assert "t_test_two_sample_sample_size(d, s, t, alpha; variance=pooled, alternative=two_sided)" in json.dumps(rec["formula"])
