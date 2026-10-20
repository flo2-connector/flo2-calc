"""The skewed distributions: lognormal, gamma and beta, each cdf, survival function and quantile.

req:skewed-distributions and cap:skewed-distributions-lognormal-gamma-beta in design
0bee0c00b35845f6 (flo2-calc 0.8.0, dec:v0-8-0-bayes-randomization-shapley-choices, choice 8).
In the rounded class beside the normal, chi-square and Student-t: every value is checked
against an independent oracle (tests/oracle.py: mpmath at 120 digits, its own gammainc and
betainc, rounded by Python's decimal module), on HARD cases next to a rounding tie, on both
sides of it. Exact where the value is rational; units and domains refused with their reasons;
rounded arguments give a bound that holds; the limits still stop it.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import oracle as O
import pytest
from conftest import graph, inp, op

from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph
from flo2_calc.numbers import decimal_text, parse_number


def run(*nodes, limits=L.LAPTOP, result=None):
    return evaluation_json(evaluate(read_graph(graph(*nodes, result=result)), L.Guard(limits)))


def ok(*nodes, **kw):
    answer = run(*nodes, **kw)
    assert answer["status"] == "ok", answer
    return answer["result"]


def refused(*nodes, **kw):
    answer = run(*nodes, **kw)
    assert answer["status"] == "refused", answer
    return answer["refused"]


def number(r: dict, unit: str = "") -> Fraction:
    text = r["value"]
    if unit:
        assert text.endswith(" " + unit), r
        text = text[: -len(unit) - 1]
    return Fraction(Decimal(text))


def text(q: Fraction) -> str:
    return decimal_text(q)


def frac(q: Fraction) -> str:
    return f"{q.numerator}/{q.denominator}"


def assert_correctly_rounded(r: dict, expected: Fraction, places: int = 30, unit: str = "") -> None:
    assert number(r, unit) == expected, (r, expected)
    assert "exact" not in r, "a rounded value is never given an exact fraction"
    label = r["rounded"]
    assert label["correctly_rounded"] is True and label["digits"] == places
    assert label["from"] == [r["node"]]


# ---------------------------------------------------------------- correct rounding next to a tie

MEDIAN, SIGMA = Fraction(20), Fraction(2, 5)
SHAPE, SCALE = Fraction(7, 2), Fraction(3, 2)
A, B = Fraction(5, 2), Fraction(7, 3)

CDFS = [
    ("lognormal_cdf", lambda x: O.lognormal_cdf(x, O.mpq(MEDIAN), O.mpq(SIGMA)), "23.1", [MEDIAN, SIGMA]),
    ("lognormal_sf", lambda x: O.lognormal_sf(x, O.mpq(MEDIAN), O.mpq(SIGMA)), "41.7", [MEDIAN, SIGMA]),
    ("gamma_cdf", lambda x: O.gamma_cdf(x, O.mpq(SHAPE), O.mpq(SCALE)), "4.4", [SHAPE, SCALE]),
    ("gamma_sf", lambda x: O.gamma_sf(x, O.mpq(SHAPE), O.mpq(SCALE)), "13.9", [SHAPE, SCALE]),
    ("beta_cdf", lambda x: O.beta_cdf(x, O.mpq(A), O.mpq(B)), "0.37", [A, B]),
    ("beta_sf", lambda x: O.beta_sf(x, O.mpq(A), O.mpq(B)), "0.62", [A, B]),
]


@pytest.mark.parametrize("name, f, start, params", CDFS, ids=[c[0] for c in CDFS])
def test_a_skewed_cdf_or_tail_is_correctly_rounded_on_both_sides_of_a_tie(name, f, start, params):
    below, above, tie = O.hard_pair(f, O.mp.mpf(start))
    got = []
    for x in (below, above):
        assert O.distance_to_tie_in_ulps(f, x, tie) < O.mp.mpf(10) ** -10, "a hard case: next to a tie"
        r = ok(inp("x", text(x)), inp("p1", frac(params[0])), inp("p2", frac(params[1])), op("y", name, "x", "p1", "p2"))
        expected = O.exact(f, x)
        assert expected in O.neighbours(tie)
        assert_correctly_rounded(r, expected)
        got.append(number(r))
    assert got[0] != got[1], "the two sides of the tie round apart"


QUANTILES = [
    ("lognormal_quantile", lambda x: O.lognormal_cdf(x, O.mpq(MEDIAN), O.mpq(SIGMA)), "27.3", [MEDIAN, SIGMA]),
    ("lognormal_quantile", lambda x: O.lognormal_cdf(x, O.mpq(MEDIAN), O.mpq(SIGMA)), "11.2", [MEDIAN, SIGMA]),
    ("gamma_quantile", lambda x: O.gamma_cdf(x, O.mpq(SHAPE), O.mpq(SCALE)), "2.6", [SHAPE, SCALE]),
    ("gamma_quantile", lambda x: O.gamma_cdf(x, O.mpq(SHAPE), O.mpq(SCALE)), "14.2", [SHAPE, SCALE]),
    ("beta_quantile", lambda x: O.beta_cdf(x, O.mpq(A), O.mpq(B)), "0.21", [A, B]),
    ("beta_quantile", lambda x: O.beta_cdf(x, O.mpq(A), O.mpq(B)), "0.93", [A, B]),
]


@pytest.mark.parametrize("name, cdf, start, params", QUANTILES, ids=[f"{c[0]}({c[2]})" for c in QUANTILES])
def test_a_skewed_quantile_is_correctly_rounded_next_to_a_tie(name, cdf, start, params):
    """p is built from a tie in x: the cdf at the tie, cut to 45 digits below and above."""
    with O.mp.workdps(O.DPS):
        tie = O.midpoint_near(O.mp.mpf(start))
        lo, hi = O.truncations(cdf(tie))
    for p, side in ((lo, 0), (hi, 1)):
        r = ok(inp("p", text(p)), inp("p1", frac(params[0])), inp("p2", frac(params[1])), op("q", name, "p", "p1", "p2"))
        assert number(r) == O.neighbours(tie)[side], "the side of the tie its p is on"
        assert O.brackets_quantile(cdf, number(r), p)
        assert r["rounded"]["correctly_rounded"] is True


@pytest.mark.parametrize("name, cdf, p, params", [
    ("gamma_quantile", lambda x: O.gamma_cdf(x, 1, 1), "1e-40", ["1", "1"]),
    ("gamma_quantile", lambda x: O.gamma_cdf(x, O.mpq(Fraction(1, 10)), 1), "0.999999999", ["1/10", "1"]),
    ("gamma_quantile", lambda x: O.gamma_cdf(x, 400, 2), "0.5", ["400", "2"]),
    ("beta_quantile", lambda x: O.beta_cdf(x, O.mpq(Fraction(1, 2)), 30), "1e-20", ["1/2", "30"]),
    ("beta_quantile", lambda x: O.beta_cdf(x, 40, O.mpq(Fraction(1, 3))), "0.99999", ["40", "1/3"]),
    ("lognormal_quantile", lambda x: O.lognormal_cdf(x, 3, 2), "1e-30", ["3", "2"]),
])
def test_a_skewed_quantile_brackets_its_p_across_its_range(name, cdf, p, params):
    r = ok(inp("p", p), inp("p1", params[0]), inp("p2", params[1]), op("q", name, "p", "p1", "p2"))
    assert O.brackets_quantile(cdf, number(r), parse_number(p)), r


def test_a_quantile_asked_for_many_digits_is_correctly_rounded_to_all_of_them():
    cdf = lambda x: O.gamma_cdf(x, O.mpq(SHAPE), O.mpq(SCALE))  # noqa: E731
    r = ok(inp("p", "0.95"), inp("k", "7/2"), inp("t", "3/2"), op("q", "gamma_quantile", "p", "k", "t", digits=80))
    assert r["rounded"]["digits"] == 80
    with O.mp.workdps(200):
        c = O.mpq(number(r))
        h = O.ulp(c, 80) / 2
        assert cdf(c - h) < O.mp.mpf("0.95") < cdf(c + h)


# ---------------------------------------------------------------- exact where rational


@pytest.mark.parametrize("nodes, expected", [
    ([inp("x", "20 ug/L"), inp("m", "20 ug/L"), inp("s", "0.4"), op("r", "lognormal_cdf", "x", "m", "s")], "0.5"),
    ([inp("x", "0.02 mg/L"), inp("m", "20 ug/L"), inp("s", "0.4"), op("r", "lognormal_sf", "x", "m", "s")], "0.5"),
    ([inp("x", "0 ug/L"), inp("m", "20 ug/L"), inp("s", "0.4"), op("r", "lognormal_cdf", "x", "m", "s")], "0"),
    ([inp("x", "-1 ug/L"), inp("m", "20 ug/L"), inp("s", "0.4"), op("r", "lognormal_sf", "x", "m", "s")], "1"),
    ([inp("p", "1/2"), inp("m", "20 ug/L"), inp("s", "0.4"), op("r", "lognormal_quantile", "p", "m", "s")], "20 ug/L"),
    ([inp("x", "0 h"), inp("k", "2"), inp("t", "3 h"), op("r", "gamma_cdf", "x", "k", "t")], "0"),
    ([inp("x", "-2 h"), inp("k", "2"), inp("t", "3 h"), op("r", "gamma_sf", "x", "k", "t")], "1"),
    # A beta with whole parameters is a binomial tail, a polynomial in x: rational at a rational x.
    ([inp("x", "1/4"), inp("a", "2"), inp("b", "3"), op("r", "beta_cdf", "x", "a", "b")], "0.26171875"),
    ([inp("x", "1/4"), inp("a", "2"), inp("b", "3"), op("r", "beta_sf", "x", "a", "b")], "0.73828125"),
    ([inp("x", "0.3"), inp("a", "1"), inp("b", "1"), op("r", "beta_cdf", "x", "a", "b")], "0.3"),
    ([inp("x", "1/2"), inp("a", "5/2"), inp("b", "5/2"), op("r", "beta_cdf", "x", "a", "b")], "0.5"),
    ([inp("x", "0"), inp("a", "5/2"), inp("b", "7/3"), op("r", "beta_cdf", "x", "a", "b")], "0"),
    ([inp("x", "1.2"), inp("a", "5/2"), inp("b", "7/3"), op("r", "beta_cdf", "x", "a", "b")], "1"),
    ([inp("p", "0.3"), inp("a", "1"), inp("b", "1"), op("r", "beta_quantile", "p", "a", "b")], "0.3"),
    ([inp("p", "1/4"), inp("a", "2"), inp("b", "1"), op("r", "beta_quantile", "p", "a", "b")], "0.5"),
    ([inp("p", "3/4"), inp("a", "1"), inp("b", "2"), op("r", "beta_quantile", "p", "a", "b")], "0.5"),
    ([inp("p", "1/2"), inp("a", "7/3"), inp("b", "7/3"), op("r", "beta_quantile", "p", "a", "b")], "0.5"),
])
def test_where_a_skewed_distributions_value_is_rational_it_stays_exact(nodes, expected):
    r = ok(*nodes)
    assert r["value"] == expected and "rounded" not in r, r


def test_an_exact_beta_value_that_is_a_rounding_tie_is_never_rounded():
    """67/256 = 0.26171875 has eight digits: asked for seven it is a tie, which
    Ziv's test could never settle. Found exact first, it is given exactly."""
    r = ok(inp("x", "1/4"), inp("a", "2"), inp("b", "3"), op("r", "beta_cdf", "x", "a", "b", digits=7))
    assert r == {"node": "r", "value": "0.26171875"}


def test_a_beta_whose_exact_value_passes_the_digits_budget_is_correctly_rounded_instead():
    nodes = [inp("x", "1/7"), inp("a", "3000"), inp("b", "2000"), op("r", "beta_sf", "x", "a", "b")]
    r = ok(*nodes, limits=L.Limits(max_digits=2000))
    assert "rounded" in r
    with O.mp.workdps(O.DPS):
        assert number(r) == O.rounded(O.beta_sf(O.mpq(Fraction(1, 7)), 3000, 2000))


# ---------------------------------------------------------------- units


def test_units_are_carried_by_the_rules():
    r = ok(inp("x", "3 h"), inp("k", "2"), inp("t", "90 min"), op("r", "gamma_cdf", "x", "k", "t"))
    with O.mp.workdps(O.DPS):
        assert number(r) == O.rounded(O.gamma_cdf(O.mpq(Fraction(3)), 2, O.mpq(Fraction(3, 2))))
    q = ok(inp("p", "0.9"), inp("k", "2"), inp("t", "1.5 h"), op("r", "gamma_quantile", "p", "k", "t"))
    assert q["value"].endswith(" h")
    m = ok(inp("p", "0.975"), inp("m", "20 ug/L"), inp("s", "0.4"), op("r", "lognormal_quantile", "p", "m", "s"))
    assert m["value"].endswith(" ug/L")
    with O.mp.workdps(O.DPS):
        assert number(m, "ug/L") == O.rounded(20 * O.mp.exp(O.mpq(Fraction(2, 5)) * O.mp.sqrt(2) * O.mp.erfinv(O.mpq(Fraction(95, 100)))))
    mixed = ok(inp("x", "0.015 mg/L"), inp("m", "20 ug/L"), inp("s", "0.4"), op("r", "lognormal_cdf", "x", "m", "s"))
    with O.mp.workdps(O.DPS):
        assert number(mixed) == O.rounded(O.lognormal_cdf(15, 20, O.mpq(Fraction(2, 5))))


@pytest.mark.parametrize("nodes, kind, words", [
    ([inp("x", "15 ug/L"), inp("m", "20 mm"), inp("s", "0.4"), op("r", "lognormal_cdf", "x", "m", "s")], "unit_mismatch", "lognormal_cdf"),
    ([inp("x", "15 ug/L"), inp("m", "20 ug/L"), inp("s", "0.4 ug/L"), op("r", "lognormal_cdf", "x", "m", "s")], "unit_mismatch", "sigma"),
    ([inp("x", "3 h"), inp("k", "2 h"), inp("t", "1 h"), op("r", "gamma_cdf", "x", "k", "t")], "unit_mismatch", "shape"),
    ([inp("x", "3 h"), inp("k", "2"), inp("t", "1 mm"), op("r", "gamma_cdf", "x", "k", "t")], "unit_mismatch", "gamma_cdf"),
    ([inp("x", "0.3 mm"), inp("a", "2"), inp("b", "3"), op("r", "beta_cdf", "x", "a", "b")], "unit_mismatch", "plain"),
    ([inp("p", "0.9 mm"), inp("a", "2"), inp("b", "3"), op("r", "beta_quantile", "p", "a", "b")], "unit_mismatch", "probability"),
    ([inp("x", "300 K"), inp("m", "25 degC"), inp("s", "0.1"), op("r", "lognormal_cdf", "x", "m", "s")], "offset_temperature", "K first"),
])
def test_a_unit_a_skewed_distribution_cannot_take_is_refused_naming_it(nodes, kind, words):
    r = refused(*nodes)
    assert r["kind"] == kind and words in r["reason"], r


# ---------------------------------------------------------------- domains


@pytest.mark.parametrize("nodes, kind, words", [
    ([inp("x", "15"), inp("m", "0"), inp("s", "0.4"), op("r", "lognormal_cdf", "x", "m", "s")], "out_of_domain", "median"),
    ([inp("x", "15"), inp("m", "20"), inp("s", "0"), op("r", "lognormal_cdf", "x", "m", "s")], "out_of_domain", "sigma"),
    ([inp("p", "0"), inp("m", "20"), inp("s", "0.4"), op("r", "lognormal_quantile", "p", "m", "s")], "out_of_domain", "strictly between 0 and 1"),
    ([inp("x", "1"), inp("k", "-1"), inp("t", "1"), op("r", "gamma_cdf", "x", "k", "t")], "out_of_domain", "shape"),
    ([inp("x", "1"), inp("k", "2"), inp("t", "0"), op("r", "gamma_sf", "x", "k", "t")], "out_of_domain", "scale"),
    ([inp("p", "1"), inp("k", "2"), inp("t", "1"), op("r", "gamma_quantile", "p", "k", "t")], "out_of_domain", "strictly between 0 and 1"),
    ([inp("x", "0.5"), inp("a", "0"), inp("b", "1"), op("r", "beta_cdf", "x", "a", "b")], "out_of_domain", "a"),
    ([inp("p", "0.5"), inp("a", "2"), inp("b", "-3"), op("r", "beta_quantile", "p", "a", "b")], "out_of_domain", "b"),
    ([inp("p", "1.5"), inp("a", "2"), inp("b", "3"), op("r", "beta_quantile", "p", "a", "b")], "out_of_domain", "strictly between 0 and 1"),
])
def test_an_argument_outside_a_skewed_distributions_domain_is_refused(nodes, kind, words):
    r = refused(*nodes)
    assert r["kind"] == kind and words in r["reason"], r


def test_the_wrong_number_of_arguments_is_a_malformed_call():
    from flo2_calc.errors import CallError

    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("x", "1"), inp("k", "2"), op("r", "gamma_cdf", "x", "k")))
    assert "exactly 3" in caught.value.problem


def test_over_an_array_a_skewed_distribution_is_refused_for_now():
    r = refused(inp("x", {"array": ["1", "2"]}), inp("k", "2"), inp("t", "1"), op("r", "gamma_cdf", "x", "k", "t"))
    assert r["kind"] == "type_mismatch" and "single values" in r["reason"]


# ---------------------------------------------------------------- rounded arguments


def test_a_rounded_argument_gives_a_skewed_value_with_a_bound_that_holds():
    nodes = [inp("two", "2"), op("r2", "sqrt", "two"), inp("ten", "10"), op("s", "div", "r2", "ten"),  # sigma = sqrt(2)/10
             inp("x", "25"), inp("m", "20"), op("c", "lognormal_cdf", "x", "m", "s"),
             inp("p", "0.9"), inp("t", "3/2"), op("g", "gamma_quantile", "p", "r2", "t"),
             op("half", "div", "r2", "two"), inp("a", "3"), op("bq", "beta_quantile", "half", "a", "r2")]
    answer = run(*nodes, result=["c", "g", "bq"])
    assert answer["status"] == "ok", answer
    by = {v["node"]: v for v in answer["values"]}
    with O.mp.workdps(O.DPS):
        sq = O.mp.sqrt(2)
        truths = {
            "c": O.lognormal_cdf(25, 20, sq / 10),
            "g": O.mp.findroot(lambda x: O.gamma_cdf(x, sq, O.mp.mpf(3) / 2) - O.mp.mpf("0.9"), 3),
            "bq": O.mp.findroot(lambda x: O.beta_cdf(x, 3, sq) - sq / 2, O.mp.mpf("0.6")),
        }
        for node, true in truths.items():
            label = by[node]["rounded"]
            assert label["correctly_rounded"] is False and node in label["from"]
            assert abs(O.mpq(number(by[node])) - true) <= O.mpq(parse_number(label["error_at_most"])), node


# ---------------------------------------------------------------- published tables


@pytest.mark.parametrize("p, k, critical", [
    # NIST/SEMATECH e-Handbook 1.3.6.7.4: the chi-square with nu degrees of freedom is the gamma of
    # shape nu/2 and scale 2. (An exact value is written without trailing zeros: 11.070 is "11.07".)
    ("0.95", "5/2", "11.07"), ("0.99", "5", "23.209"), ("0.95", "1/2", "3.841"),
])
def test_the_gamma_quantile_gives_the_published_chi_square_critical_values(p, k, critical):
    assert ok(inp("p", p), inp("k", k), inp("t", "2"), op("q", "gamma_quantile", "p", "k", "t"),
              op("r", "round", "q", places=3)) == {"node": "r", "value": critical}


def test_the_lognormal_quantile_is_the_median_times_e_to_the_normal_quantile():
    """NIST 1.3.6.7.1: z(0.975) = 1.96, so the 97.5th percentile of a lognormal of median 1 and sigma 1 is e^1.96 to 2 places."""
    assert ok(inp("p", "0.975"), inp("m", "1"), inp("s", "1"), op("q", "lognormal_quantile", "p", "m", "s"),
              op("r", "round", "q", places=2)) == {"node": "r", "value": "7.1"}


# ---------------------------------------------------------------- limits, labels and the record


def test_a_skewed_value_past_the_digits_budget_is_stopped_not_guessed():
    r = refused(inp("x", "1"), inp("k", "2"), inp("t", "1"), op("r", "gamma_cdf", "x", "k", "t", digits=900), limits=L.Limits(max_digits=500))
    assert r["kind"] == "exceeds_limits" and r["limit"]["name"] == "max_digits"


def test_a_far_tail_too_small_to_carry_is_stopped():
    r = refused(inp("x", "1e6"), inp("k", "2"), inp("t", "1"), op("r", "gamma_sf", "x", "k", "t"), limits=L.FLO2_IO)
    assert r["kind"] == "exceeds_limits"


def test_the_skewed_distributions_are_in_a_record_that_re_runs_and_shown_back():
    nodes = [inp("x", "31 ug/L", "the person's lab value"), inp("m", "20 ug/L", "published reference: geometric mean"),
             inp("s", "0.4", "published reference: ln of the geometric sd"), op("above", "lognormal_sf", "x", "m", "s"),
             inp("p", "0.975", "the reference range's upper end"), op("upper", "lognormal_quantile", "p", "m", "s"),
             inp("k", "3", "fit"), inp("t", "2 h", "fit"), inp("w", "9 h", "wait"), op("g", "gamma_sf", "w", "k", "t"),
             inp("a", "2", "fit"), inp("b", "5", "fit"), inp("f", "0.4", "share"), op("bc", "beta_cdf", "f", "a", "b"),
             op("bq", "beta_quantile", "p", "a", "b")]
    ev = evaluate(read_graph(graph(*nodes, result=["above", "upper", "g", "bc", "bq"])))
    assert ev.ok, ev.refusal
    rec = R.build(ev, "skewed", None)
    assert rec["schema_version"] == 10
    import jsonschema

    jsonschema.Draft202012Validator(R.schema()).validate(rec)
    lines = {f["node"]: f["text"] for f in rec["formula"]}
    assert lines["above"].startswith("above = lognormal_sf(x, m, s) ≈ 0.")
    assert lines["bc"] == "bc = beta_cdf(f, a, b) = 0.76672", "a whole-parameter beta is exact"
    assert R.rerun(rec)["reproduces"] is True
