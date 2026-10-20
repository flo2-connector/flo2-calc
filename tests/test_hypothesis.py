"""The named hypothesis tests: each a kept record with its statistic, p-value, sidedness, degrees of
freedom, assumptions and the decision at a stated alpha.

req:calc-computes-named-hypothesis-tests-as-kept-records in design 0bee0c00b35845f6 (flo2-calc 0.10.0,
option (a) of dec:idea-how-a-statistical-hypothesis-test-is-designed-computed-and-read). Pinned as a
CLASS: every named test's record carries the same fields, every alternative is stated and never
defaulted, and every decision reads "reject H0 at α" or "fail to reject H0 at α", never more.

Reference values, and where each comes from:
- PUBLISHED: Student's sleep data (Cushny and Peebles 1905, R's `sleep`), as R's t.test prints them:
  Welch t = -1.8608, df = 17.776, p = 0.07939; pooled df = 18, p = 0.07919; paired (a one-sample test
  of the differences) t = -4.0621, df = 9, p = 0.002833. Mendel's peas (R's binom.test example):
  682 of 925 against 3/4, p = 0.3825. Agresti's party by gender table (R's chisq.test example):
  X-squared = 30.07, df = 2, p = 2.954e-07. Fisher's lady tasting tea: 17/70 one-sided, 34/70 two-sided.
  Mendel's dihybrid cross 315/108/101/32 against 9:3:3:1: X-squared = 0.470, df = 3, p = 0.9254.
- INDEPENDENT COMPUTATION: mpmath (not Arb) at 120 digits, through a different route from flo2-calc's:
  the Student-t tail as mpmath's own incomplete beta (to the 30th digit, correctly rounded) AND as a
  numerical integral of the t density (to 1e-25); the normal tail as mpmath's erfc; the chi-square tail
  as mpmath's incomplete gamma. The exact tests (binomial, Fisher) against an enumeration written here,
  in exact fractions.
"""

from __future__ import annotations

import json
from fractions import Fraction
from typing import Any

import anyio
import jsonschema
import mpmath as mp
import pytest
from conftest import answer_of, graph, inp, op, session
from oracle import mpq, rounded

from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph
from flo2_calc.numbers import parse_number

SLEEP_1 = ["0.7", "-1.6", "-0.2", "-1.2", "-0.1", "3.4", "3.7", "0.8", "0.0", "2.0"]
SLEEP_2 = ["1.9", "0.8", "1.1", "0.1", "-0.1", "4.4", "5.5", "1.6", "4.6", "3.4"]
SRC = "Cushny and Peebles (1905), extra hours of sleep (R's sleep data)"

BLOCK_FIELDS = {"test", "title", "h0", "h1", "alternative", "sidedness", "alpha", "n", "statistic", "p_value",
                "p_value_method", "assumptions", "decision", "reject_h0"}


def run(*nodes: dict, result: Any = None, limits: L.Limits = L.LAPTOP) -> dict:
    return evaluation_json(evaluate(read_graph(graph(*nodes, result=result)), L.Guard(limits)))


def entry(answer: dict, node: str = "p") -> dict:
    assert answer["status"] == "ok", answer.get("refused")
    return next(v for v in answer["values"] if v["node"] == node)


def block(answer: dict, node: str = "p") -> dict:
    return entry(answer, node)["hypothesis_test"]


def value_of(v: dict) -> Fraction:
    """A value as written: its exact fraction where it has one, else its decimal."""
    if "exact" in v:
        return Fraction(v["exact"].split(" ")[0])
    return parse_number(v["value"].split(" ")[0])


def alpha(a: str = "0.05") -> dict:
    return inp("alpha", a, {"design_node": "con:significance-level"})


def arr(id_: str, xs: list[str], unit: str = "", source: str = SRC) -> dict:
    value: dict[str, Any] = {"array": xs}
    if unit:
        value["unit"] = unit
    return inp(id_, value, source)


def sig(x: Fraction, digits: int) -> str:
    return mp.nstr(mpq(x), digits)


# ---------------------------------------------------------------- the independent oracles


def t_tail_two_sided(t2: Fraction, nu: Fraction) -> mp.mpf:
    """P(|T| > |t|) by mpmath's incomplete beta, at 120 digits."""
    with mp.workdps(120):
        return mp.betainc(mpq(nu) / 2, mp.mpf(1) / 2, 0, mpq(nu) / (mpq(nu) + mpq(t2)), regularized=True)


def t_tail_by_integral(t: mp.mpf, nu: Fraction) -> mp.mpf:
    """P(T > t) by integrating Student's density: a route that shares nothing with the incomplete beta."""
    with mp.workdps(60):
        v = mpq(nu)
        c = mp.gamma((v + 1) / 2) / (mp.sqrt(v * mp.pi) * mp.gamma(v / 2))
        return mp.quad(lambda x: c * (1 + x * x / v) ** (-(v + 1) / 2), [t, t + 10, mp.inf])


def welch(xs: list[str], ys: list[str]) -> tuple[Fraction, Fraction, Fraction]:
    """(mean difference, t^2, Welch's degrees of freedom), in exact fractions."""
    a, b = [parse_number(x) for x in xs], [parse_number(y) for y in ys]
    ma, mb = sum(a, Fraction(0)) / len(a), sum(b, Fraction(0)) / len(b)
    va = sum(((x - ma) ** 2 for x in a), Fraction(0)) / (len(a) - 1)
    vb = sum(((y - mb) ** 2 for y in b), Fraction(0)) / (len(b) - 1)
    ua, ub = va / len(a), vb / len(b)
    return ma - mb, (ma - mb) ** 2 / (ua + ub), (ua + ub) ** 2 / (ua**2 / (len(a) - 1) + ub**2 / (len(b) - 1))


def binomial_weights(n: int, p: Fraction) -> list[Fraction]:
    return [Fraction(mp_comb(n, i)) * p**i * (1 - p) ** (n - i) for i in range(n + 1)]


def mp_comb(n: int, k: int) -> int:
    from math import comb

    return comb(n, k)


def hypergeometric(r1: int, r2: int, c1: int) -> dict[int, Fraction]:
    total = mp_comb(r1 + r2, c1)
    return {x: Fraction(mp_comb(r1, x) * mp_comb(r2, c1 - x), total) for x in range(max(0, c1 - r2), min(r1, c1) + 1)}


# ---------------------------------------------------------------- the t-tests on Student's sleep data


def test_welchs_t_test_on_the_sleep_data_matches_r_and_an_independent_computation():
    ans = run(arr("a", SLEEP_1, "h"), arr("b", SLEEP_2, "h"), alpha(),
              op("p", "t_test_two_sample", "a", "b", "alpha", variance="welch", alternative="two_sided"))
    b = block(ans)
    diff, t2, nu = welch(SLEEP_1, SLEEP_2)
    # published (R's t.test): t = -1.8608, df = 17.776, p-value = 0.07939
    assert b["statistic"]["name"] == "t" and sig(value_of(b["statistic"]), 5) == "-1.8608"
    assert value_of(b["dof"]) == nu, "Welch's degrees of freedom are exact for exact data"
    assert sig(nu, 5) == "17.776"
    p = value_of(b["p_value"])
    assert sig(p, 4) == "0.07939"
    # independent: mpmath's incomplete beta, correctly rounded to the 30th digit; and the t density's integral
    assert p == rounded(t_tail_two_sided(t2, nu))
    with mp.workdps(60):
        assert abs(mpq(p) - 2 * t_tail_by_integral(mp.sqrt(mpq(t2)), nu)) < mp.mpf(10) ** -25
    assert b["p_value"]["rounded"]["correctly_rounded"] is True
    assert b["variance"] == "welch" and "Welch" in b["p_value_method"]
    assert b["decision"] == "fail to reject H0 at α = 0.05" and b["reject_h0"] is False
    assert b["n"] == ["10", "10"]
    assert entry(ans)["value"] == b["p_value"]["value"], "the node's value is the p-value"


def test_the_pooled_t_test_on_the_sleep_data_matches_r():
    ans = run(arr("a", SLEEP_1, "h"), arr("b", SLEEP_2, "h"), alpha(),
              op("p", "t_test_two_sample", "a", "b", "alpha", variance="pooled", alternative="two_sided"))
    b = block(ans)
    assert value_of(b["dof"]) == 18 and sig(value_of(b["statistic"]), 5) == "-1.8608"
    assert sig(value_of(b["p_value"]), 4) == "0.07919"
    assert any("equal variances" in a for a in b["assumptions"])


def test_the_paired_t_test_is_a_one_sample_test_of_the_differences_and_matches_r():
    diffs = [f"{d.numerator}/{d.denominator}" for d in (parse_number(y) - parse_number(x) for x, y in zip(SLEEP_1, SLEEP_2))]
    ans = run(arr("d", diffs, "h"), inp("mu0", "0 h", "H0: no difference"), alpha(),
              op("p", "t_test_one_sample", "d", "mu0", "alpha", alternative="two_sided"))
    b = block(ans)
    # published (R, paired = TRUE): t = -4.0621, df = 9, p-value = 0.002833 (signs: drug 1 minus drug 2)
    assert sig(abs(value_of(b["statistic"])), 5) == "4.0621" and value_of(b["dof"]) == 9
    assert sig(value_of(b["p_value"]), 4) == "0.002833"
    assert b["decision"] == "reject H0 at α = 0.05" and b["reject_h0"] is True


def test_a_t_test_from_a_summary_gives_exactly_what_the_data_give():
    """The summary form takes (mean, sd, n). Given the sd the data have, it is the same test to every digit: the
    samples here are chosen so each sample sd is rational (0, 2, 4: mean 2, sd 2; 3, 6, 9: mean 6, sd 3)."""
    one_data = run(arr("y", ["0", "2", "4"], "mm"), inp("mu0", "1 mm", "H0"), alpha(),
                   op("p", "t_test_one_sample", "y", "mu0", "alpha", alternative="greater"))
    one_summary = run(inp("m", "2 mm", "summary"), inp("s", "2 mm", "summary"), inp("n", "3", "summary"),
                      inp("mu0", "1 mm", "H0"), alpha(),
                      op("p", "t_test_one_sample", "m", "s", "n", "mu0", "alpha", alternative="greater"))
    assert block(one_summary)["p_value"] == block(one_data)["p_value"]
    assert value_of(block(one_summary)["dof"]) == 2 and block(one_summary)["n"] == ["3"]
    two_data = run(arr("x", ["0", "2", "4"], "mm"), arr("y", ["3", "6", "9"], "mm"), alpha(),
                   op("p", "t_test_two_sample", "x", "y", "alpha", variance="welch", alternative="less"))
    two_summary = run(inp("mx", "2 mm"), inp("sx", "2 mm"), inp("nx", "3"), inp("my", "6 mm"), inp("sy", "3 mm"),
                      inp("ny", "3"), alpha(),
                      op("p", "t_test_two_sample", "mx", "sx", "nx", "my", "sy", "ny", "alpha", variance="welch",
                         alternative="less"))
    assert block(two_summary)["p_value"] == block(two_data)["p_value"]
    assert block(two_summary)["dof"] == block(two_data)["dof"]
    z_summary = run(inp("m", "2 mm"), inp("n", "3"), inp("mu0", "1 mm"), inp("s", "2 mm"), alpha(),
                    op("p", "z_test", "m", "n", "mu0", "s", "alpha", alternative="greater"))
    z_data = run(arr("y", ["0", "2", "4"], "mm"), inp("mu0", "1 mm"), inp("s", "2 mm"), alpha(),
                 op("p", "z_test", "y", "mu0", "s", "alpha", alternative="greater"))
    assert block(z_summary)["p_value"] == block(z_data)["p_value"]


def test_one_sided_and_two_sided_p_values_agree_with_each_other():
    out = {}
    for alt in ("greater", "less", "two_sided"):
        ans = run(arr("a", SLEEP_1, "h"), arr("b", SLEEP_2, "h"), alpha(),
                  op("p", "t_test_two_sample", "a", "b", "alpha", variance="pooled", alternative=alt))
        out[alt] = value_of(block(ans)["p_value"])
    # t < 0 here: "less" is half the two-sided p, "greater" is the rest (to within each one's rounding)
    assert abs(out["less"] * 2 - out["two_sided"]) < Fraction(1, 10**28)
    assert abs(out["greater"] + out["less"] - 1) < Fraction(1, 10**28)


# ---------------------------------------------------------------- the z-test


@pytest.mark.parametrize("alt", ["greater", "less", "two_sided"])
def test_the_z_test_matches_the_normal_tail(alt):
    xs = ["101.2", "99.8", "102.5", "100.9", "103.1", "98.7", "101.6", "102.2"]
    ans = run(arr("x", xs, "g", "eight fills"), inp("mu0", "100 g", "label weight"), inp("sigma", "1.5 g", "filler spec"),
              alpha(), op("p", "z_test", "x", "mu0", "sigma", "alpha", alternative=alt))
    b = block(ans)
    xbar = sum(map(parse_number, xs), Fraction(0)) / len(xs)
    z2 = (xbar - 100) ** 2 * len(xs) / Fraction(9, 4)
    with mp.workdps(120):
        z = mp.sqrt(mpq(z2))
        tail = {"greater": mp.erfc(z / mp.sqrt(2)) / 2, "less": 1 - mp.erfc(z / mp.sqrt(2)) / 2,
                "two_sided": mp.erfc(z / mp.sqrt(2))}[alt]
    assert value_of(b["p_value"]) == rounded(tail)
    assert "dof" not in b and b["statistic"]["name"] == "z"
    assert any("known" in a for a in b["assumptions"])
    summary = run(inp("m", f"{xbar.numerator}/{xbar.denominator} g", "the mean of the eight"), inp("n", "8", "fills"),
                  inp("mu0", "100 g", "label"), inp("sigma", "1.5 g", "spec"), alpha(),
                  op("p", "z_test", "m", "n", "mu0", "sigma", "alpha", alternative=alt))
    assert block(summary)["p_value"] == b["p_value"], "the summary gives exactly what the data give"


def test_a_z_of_zero_gives_an_exact_p_value():
    ans = run(arr("x", ["99", "101"], "g"), inp("mu0", "100 g", "H0"), inp("s", "2 g", "spec"), alpha(),
              op("p", "z_test", "x", "mu0", "s", "alpha", alternative="two_sided"),
              op("q", "z_test", "x", "mu0", "s", "alpha", alternative="greater"), result=["p", "q"])
    assert entry(ans, "p")["value"] == "1" and "rounded" not in entry(ans, "p")
    assert entry(ans, "q")["value"] == "0.5"


# ---------------------------------------------------------------- chi-square tests


def test_chi_square_goodness_of_fit_on_mendels_peas():
    obs = arr("obs", ["315", "108", "101", "32"], "", "Mendel (1866), dihybrid cross")
    for expected in (["9/16", "3/16", "3/16", "1/16"], ["312.75", "104.25", "104.25", "34.75"]):
        ans = run(obs, arr("exp", expected, "", "9:3:3:1"), alpha(),
                  op("p", "chi2_goodness_of_fit", "obs", "exp", "alpha"))
        b = block(ans)
        x2 = value_of(b["statistic"])
        assert b["statistic"]["name"] == "X2" and sig(x2, 3) == "0.47" and value_of(b["dof"]) == 3
        assert x2 == sum(((o - e) ** 2 / e for o, e in zip((315, 108, 101, 32), map(Fraction, ("312.75", "104.25", "104.25", "34.75")))), Fraction(0))
        with mp.workdps(120):
            assert value_of(b["p_value"]) == rounded(mp.gammainc(mp.mpf(3) / 2, mpq(x2) / 2, mp.inf, regularized=True))
        assert sig(value_of(b["p_value"]), 4) == "0.9254"
        assert b["alternative"] == "upper_tail" and "5" in b["p_value_method"]
        assert b["n"] == ["556"]


def test_chi_square_independence_on_agrestis_table():
    t = inp("t", {"array": [["762", "327", "468"], ["484", "239", "477"]]}, "Agresti (2007), party by gender")
    b = block(run(t, alpha(), op("p", "chi2_independence", "t", "alpha")))
    # published (R's chisq.test): X-squared = 30.07, df = 2, p-value = 2.954e-07
    assert sig(value_of(b["statistic"]), 4) == "30.07" and value_of(b["dof"]) == 2
    assert sig(value_of(b["p_value"]), 4) == "2.954e-7"
    assert b["reject_h0"] is True and b["n"] == ["2757"]
    assert any("continuity" in a for a in b["assumptions"]) or "continuity" in b["p_value_method"]


def test_a_chi_square_test_whose_expected_counts_are_below_5_is_refused_not_approximated():
    ans = run(arr("obs", ["3", "1", "6"]), arr("exp", ["1/3", "1/3", "1/3"]), alpha(),
              op("p", "chi2_goodness_of_fit", "obs", "exp", "alpha"))
    assert ans["status"] == "refused" and ans["refused"]["kind"] == "assumption_fails"
    assert "10/3" in ans["refused"]["reason"] or "3.33" in ans["refused"]["reason"]
    assert "5" in ans["refused"]["reason"]
    small = run(inp("t", {"array": [["3", "1"], ["1", "3"]]}), alpha(), op("p", "chi2_independence", "t", "alpha"))
    assert small["refused"]["kind"] == "assumption_fails" and "fisher_exact" in small["refused"]["reason"]


def test_expected_values_that_are_neither_proportions_nor_counts_are_refused():
    ans = run(arr("obs", ["30", "30"]), arr("exp", ["1/2", "1/3"]), alpha(),
              op("p", "chi2_goodness_of_fit", "obs", "exp", "alpha"))
    assert ans["refused"]["kind"] == "out_of_domain" and "sum" in ans["refused"]["reason"]


# ---------------------------------------------------------------- the exact tests


def test_the_exact_binomial_test_on_mendels_peas_matches_r_and_an_enumeration():
    nodes = (inp("k", "682", "Mendel's peas, smooth"), inp("n", "925", "peas counted"), inp("p0", "3/4", "Mendel's 3:1"), alpha())
    b = block(run(*nodes, op("p", "binomial_test", "k", "n", "p0", "alpha", alternative="two_sided")))
    w = binomial_weights(925, Fraction(3, 4))
    exact = sum((x for x in w if x <= w[682]), Fraction(0))
    assert value_of(b["p_value"]) == exact and "rounded" not in b["p_value"]
    assert sig(exact, 4) == "0.3825"  # published: R's binom.test(682, 925, p = 0.75)
    assert b["statistic"]["name"] == "k" and value_of(b["statistic"]) == 682 and "dof" not in b
    assert b["p_value_method"].startswith("exact")
    g = block(run(*nodes, op("p", "binomial_test", "k", "n", "p0", "alpha", alternative="greater")))
    assert value_of(g["p_value"]) == sum(w[682:], Fraction(0))
    le = block(run(*nodes, op("p", "binomial_test", "k", "n", "p0", "alpha", alternative="less")))
    assert value_of(le["p_value"]) == sum(w[:683], Fraction(0))


@pytest.mark.parametrize("alt, p", [("greater", Fraction(17, 70)), ("less", Fraction(69, 70)), ("two_sided", Fraction(34, 70))])
def test_fishers_exact_test_on_the_lady_tasting_tea(alt, p):
    b = block(run(inp("t", {"array": [["3", "1"], ["1", "3"]]}, "Fisher (1935), the lady tasting tea"), alpha(),
                  op("p", "fisher_exact", "t", "alpha", alternative=alt)))
    assert value_of(b["p_value"]) == p
    assert b["statistic"]["name"] == "a" and value_of(b["statistic"]) == 3
    assert b["reject_h0"] is False


def test_fisher_against_a_hypergeometric_enumeration():
    table = [[7, 2], [3, 11]]
    h = hypergeometric(9, 14, 10)
    two = sum((v for v in h.values() if v <= h[7]), Fraction(0))
    b = block(run(inp("t", {"array": [[str(c) for c in r] for r in table]}), alpha(),
                  op("p", "fisher_exact", "t", "alpha", alternative="two_sided")))
    assert value_of(b["p_value"]) == two and b["n"] == ["9", "14"]


def test_a_p_value_equal_to_alpha_rejects():
    b = block(run(inp("t", {"array": [["3", "1"], ["1", "3"]]}), inp("alpha", "17/70", "chosen to meet the p"),
                  op("p", "fisher_exact", "t", "alpha", alternative="greater")))
    assert b["reject_h0"] is True and b["decision"] == "reject H0 at α = 17/70"


def test_the_decision_is_decided_on_the_true_p_value_not_its_shown_digits():
    """p = 0.07939 shown to 1 digit is 0.08; against α = 0.08 the decision is still the true one: p < α."""
    ans = run(arr("a", SLEEP_1, "h"), arr("b", SLEEP_2, "h"), inp("alpha", "0.08", "chosen"),
              op("p", "t_test_two_sample", "a", "b", "alpha", variance="welch", alternative="two_sided", digits=1))
    b = block(ans)
    assert b["p_value"]["value"] == "0.08" and b["reject_h0"] is True


# ---------------------------------------------------------------- the class: same fields, nothing defaulted

ALL_TESTS = [
    ("z_test", [arr("x", ["1", "2", "3", "5"], "mm"), inp("m0", "2 mm"), inp("s", "1 mm"), alpha()], ["x", "m0", "s", "alpha"], {"alternative": "greater"}),
    ("t_test_one_sample", [arr("x", ["1", "2", "3", "5"], "mm"), inp("m0", "2 mm"), alpha()], ["x", "m0", "alpha"], {"alternative": "two_sided"}),
    ("t_test_two_sample", [arr("x", SLEEP_1, "h"), arr("y", SLEEP_2, "h"), alpha()], ["x", "y", "alpha"], {"alternative": "two_sided", "variance": "welch"}),
    ("chi2_goodness_of_fit", [arr("o", ["30", "20", "50"]), arr("e", ["1/4", "1/4", "1/2"]), alpha()], ["o", "e", "alpha"], {}),
    ("chi2_independence", [inp("t", {"array": [["20", "30"], ["25", "25"]]}), alpha()], ["t", "alpha"], {}),
    ("binomial_test", [inp("k", "7"), inp("n", "20"), inp("p0", "1/2"), alpha()], ["k", "n", "p0", "alpha"], {"alternative": "less"}),
    ("fisher_exact", [inp("t", {"array": [["8", "2"], ["1", "5"]]}), alpha()], ["t", "alpha"], {"alternative": "two_sided"}),
]


@pytest.mark.parametrize("name, nodes, args, fields", ALL_TESTS, ids=[t[0] for t in ALL_TESTS])
def test_every_named_test_keeps_the_same_fields(name, nodes, args, fields):
    ans = run(*nodes, op("p", name, *args, **fields))
    b = block(ans)
    assert BLOCK_FIELDS <= set(b), BLOCK_FIELDS - set(b)
    extra = set(b) - BLOCK_FIELDS
    assert extra <= {"dof", "variance"}, extra
    assert ("dof" in b) == (name in ("t_test_one_sample", "t_test_two_sample", "chi2_goodness_of_fit", "chi2_independence"))
    assert b["test"] == name and b["alpha"]["node"] == "alpha" and b["alpha"]["value"] == "0.05"
    assert b["alpha"]["source"] == {"design_node": "con:significance-level"}
    assert b["decision"] in ("reject H0 at α = 0.05", "fail to reject H0 at α = 0.05")
    assert b["reject_h0"] is (b["decision"].startswith("reject"))
    assert b["assumptions"] and all(isinstance(a, str) and a for a in b["assumptions"])
    assert "prove" not in json.dumps(b).lower(), "a test never proves anything"
    assert entry(ans)["value"] == b["p_value"]["value"]
    # the working step shows the statistic and the decision
    assert "reject_H0" in json.dumps(ans["working"])
    # and its record fits the schema and re-runs (0.10.0's measurement found an exact plan's empty detail did not)
    rec = R.build(evaluate(read_graph(graph(*nodes, op("p", name, *args, **fields)))), "p-record", None)
    jsonschema.Draft202012Validator(R.schema()).validate(rec)
    assert R.rerun(R.load(rec))["reproduces"] is True


@pytest.mark.parametrize("name, nodes, args, fields", [t for t in ALL_TESTS if t[3].get("alternative")],
                         ids=[t[0] for t in ALL_TESTS if t[3].get("alternative")])
def test_the_alternative_is_never_defaulted(name, nodes, args, fields):
    without = {k: v for k, v in fields.items() if k != "alternative"}
    with pytest.raises(CallError, match='needs "alternative"'):
        read_graph(graph(*nodes, op("p", name, *args, **without)))
    with pytest.raises(CallError, match="'both' is not an alternative"):
        read_graph(graph(*nodes, op("p", name, *args, **{**fields, "alternative": "both"})))


def test_the_two_sample_t_test_must_say_welch_or_pooled():
    nodes = [arr("x", SLEEP_1, "h"), arr("y", SLEEP_2, "h"), alpha()]
    with pytest.raises(CallError, match='needs "variance"'):
        read_graph(graph(*nodes, op("p", "t_test_two_sample", "x", "y", "alpha", alternative="two_sided")))
    with pytest.raises(CallError, match='only the two-sample t-test and its plans take "variance"'):
        read_graph(graph(*nodes, op("p", "t_test_one_sample", "x", "y", "alpha", alternative="two_sided", variance="welch")))


def test_a_chi_square_test_takes_no_alternative():
    with pytest.raises(CallError, match='takes no "alternative"'):
        read_graph(graph(arr("o", ["30", "70"]), arr("e", ["1/2", "1/2"]), alpha(),
                         op("p", "chi2_goodness_of_fit", "o", "e", "alpha", alternative="greater")))


@pytest.mark.parametrize("args", [["x", "alpha"], ["x", "m0", "s", "alpha"]])
def test_a_one_sample_t_test_takes_the_data_or_its_summary_and_nothing_between(args):
    with pytest.raises(CallError, match="the data or its summary"):
        read_graph(graph(arr("x", ["1", "2"]), inp("m0", "1"), inp("s", "1"), alpha(),
                         op("p", "t_test_one_sample", *args, alternative="greater")))


REFUSED = [
    ("alpha is 0", [inp("alpha", "0")], "z_test", "out_of_domain"),
    ("alpha is 1", [inp("alpha", "1")], "z_test", "out_of_domain"),
    ("alpha has a unit", [inp("alpha", "5 %")], "z_test", None),  # 5 % is 0.05, a plain number: accepted
    ("alpha is rounded", [inp("a50", "1/50"), op("alpha", "sqrt", "a50")], "z_test", "out_of_domain"),
]


@pytest.mark.parametrize("why, alpha_nodes, name, kind", REFUSED, ids=[r[0] for r in REFUSED])
def test_alpha_is_an_exact_probability_strictly_between_0_and_1(why, alpha_nodes, name, kind):
    ans = run(arr("x", ["1", "2", "3"], "mm"), inp("m0", "2 mm"), inp("s", "1 mm"), *alpha_nodes,
              op("p", "z_test", "x", "m0", "s", "alpha", alternative="greater"))
    if kind is None:
        assert ans["status"] == "ok" and block(ans)["alpha"]["value"] == "0.05"
    else:
        assert ans["status"] == "refused" and ans["refused"]["kind"] == kind and "alpha" in ans["refused"]["reason"]


def test_what_a_test_cannot_compute_is_refused_with_its_reason():
    cases = [
        (run(arr("x", ["2"], "mm"), inp("m0", "1 mm"), alpha(), op("p", "t_test_one_sample", "x", "m0", "alpha", alternative="greater")),
         "undefined", "2"),
        (run(arr("x", ["2", "2", "2"], "mm"), inp("m0", "1 mm"), alpha(), op("p", "t_test_one_sample", "x", "m0", "alpha", alternative="greater")),
         "undefined", "variance"),
        (run(arr("x", ["1", "2"], "mm"), inp("m0", "1 g"), alpha(), op("p", "t_test_one_sample", "x", "m0", "alpha", alternative="greater")),
         "unit_mismatch", ""),
        (run(inp("k", "7"), inp("n", "5"), inp("p0", "1/2"), alpha(), op("p", "binomial_test", "k", "n", "p0", "alpha", alternative="less")),
         "out_of_domain", "k"),
        (run(inp("k", "2"), inp("n", "5"), inp("p0", "1"), alpha(), op("p", "binomial_test", "k", "n", "p0", "alpha", alternative="less")),
         "out_of_domain", "p0"),
        (run(inp("t", {"array": [["1", "2", "3"], ["4", "5", "6"]]}), alpha(), op("p", "fisher_exact", "t", "alpha", alternative="less")),
         "shape_mismatch", "2 x 2"),
        (run(inp("t", {"array": [["1.5", "2"], ["4", "5"]]}), alpha(), op("p", "fisher_exact", "t", "alpha", alternative="less")),
         "out_of_domain", "whole"),
        (run(arr("o", ["30", "-2"]), arr("e", ["1/2", "1/2"]), alpha(), op("p", "chi2_goodness_of_fit", "o", "e", "alpha")),
         "out_of_domain", "count"),
    ]
    for ans, kind, word in cases:
        assert ans["status"] == "refused", ans
        assert ans["refused"]["kind"] == kind, ans["refused"]
        assert word in ans["refused"]["reason"], ans["refused"]["reason"]


# ---------------------------------------------------------------- the record


def test_a_named_test_is_kept_as_a_record_that_re_runs():
    g = graph(arr("a", SLEEP_1, "h"), arr("b", SLEEP_2, "h"), alpha(),
              op("p", "t_test_two_sample", "a", "b", "alpha", variance="welch", alternative="two_sided"),
              inp("t", {"array": [["3", "1"], ["1", "3"]]}, "Fisher (1935)"),
              op("f", "fisher_exact", "t", "alpha", alternative="greater"), result=["p", "f"])
    ev = evaluate(read_graph(g))
    rec = R.build(ev, "sleep-and-tea", {"design_node": "req:h1-drug-2-adds-sleep"})
    jsonschema.Draft202012Validator(R.schema()).validate(rec)
    assert rec["schema_version"] == 10
    kept = {v["node"]: v for v in rec["values"]}
    assert kept["p"]["hypothesis_test"]["decision"] == "fail to reject H0 at α = 0.05"
    assert kept["f"]["hypothesis_test"]["p_value"]["exact"] == "17/70"
    assert R.rerun(R.load(rec))["reproduces"] is True
    tampered = json.loads(json.dumps(rec))
    tampered["values"][[v["node"] for v in rec["values"]].index("p")]["hypothesis_test"]["decision"] = "reject H0 at α = 0.05"
    tampered["content_hash"] = R.content_hash(tampered)
    again = R.rerun(R.load(tampered))
    assert again["reproduces"] is False


def test_the_formula_names_the_test_and_its_fields():
    ans = run(arr("a", SLEEP_1, "h"), arr("b", SLEEP_2, "h"), alpha(),
              op("p", "t_test_two_sample", "a", "b", "alpha", variance="welch", alternative="two_sided"))
    text = json.dumps(ans["formula"])
    assert "t_test_two_sample(a, b, alpha; variance=welch, alternative=two_sided)" in text


def test_a_named_test_over_mcp():
    g = graph(inp("t", {"array": [["3", "1"], ["1", "3"]]}, "Fisher (1935)"), alpha(),
              op("p", "fisher_exact", "t", "alpha", alternative="two_sided"))

    async def calls():
        async with session() as s:
            answer = answer_of(await s.call_tool("evaluate_graph", {"graph": g}))
            listed = {t.name: t for t in (await s.list_tools()).tools}
            return answer, json.dumps(listed["evaluate_graph"].input_schema)

    ans, schema_text = anyio.run(calls)
    for name in ("z_test (", "t_test_two_sample (", "chi2_independence (", "binomial_test (", "fisher_exact (",
                 "t_test_two_sample_power (", "fisher_exact_sample_size ("):
        assert name in schema_text, name
    assert ans["result"]["exact"] == "17/35"
    assert ans["result"]["hypothesis_test"]["decision"] == "fail to reject H0 at α = 0.05"
