"""The rounded class: pi and e, roots, exp and logarithms, non-whole powers,
trigonometry, deg-rad conversion, rounding, and the distributions.

dec:round-1-fixes-one-to-six (groups 1, 2, 5 and 6) in design 0bee0c00b35845f6.
Every rounded value is checked against an independent oracle (tests/oracle.py:
mpmath at 120 digits, rounded by Python's decimal module), on HARD cases built
to lie within about 1e-15 of a unit in the 30th digit from a rounding tie, on
both sides of it. Exact results stay exact; units and domains are refused
with their reasons; the labels reach the record; the limits still stop it.

ver:rounded-results-are-correctly-rounded, ver:exact-results-stay-exact,
ver:new-operators-keep-the-unit-rules, ver:out-of-domain-is-refused,
ver:rounded-labels-reach-the-record, ver:limits-hold-for-rounded-results and
ver:distributions-match-an-independent-reference.
"""

from __future__ import annotations

import json
from decimal import Decimal
from fractions import Fraction

import jsonschema
import mpmath as mp
import oracle as O
import pytest
from conftest import graph, inp, op

from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc.errors import CallError
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
    return Fraction(Decimal(text))  # Decimal, not parse_number: a rounded value may have 1000 digits


def text(q: Fraction) -> str:
    return decimal_text(q)


def assert_correctly_rounded(r: dict, expected: Fraction, places: int = 30, unit: str = "") -> None:
    assert number(r, unit) == expected, (r, expected)
    assert "exact" not in r, "a rounded value is never given an exact fraction"
    label = r["rounded"]
    assert label["correctly_rounded"] is True and label["digits"] == places
    assert label["from"] == [r["node"]]
    exponent = (Decimal(expected.numerator) / Decimal(expected.denominator)).adjusted()  # exact: a short decimal
    half = Fraction(1, 2) * Fraction(10) ** (exponent - places + 1)
    assert parse_number(label["error_at_most"].split()[0]) == half, "half a unit in the last place"


# ---------------------------------------------------------------- correct rounding on hard cases

# (operator, its mpmath function of x, a starting x, extra args (exact), extra node fields, unit of x)
ONE_ARG = [
    ("sqrt", mp.sqrt, "2", {}, ""),
    ("sqrt", mp.sqrt, "0.0123", {}, ""),
    ("exp", mp.exp, "2.5", {}, ""),
    ("exp", mp.exp, "-40.1", {}, ""),
    ("ln", mp.log, "990000", {}, ""),
    ("ln", mp.log, "0.75", {}, ""),
    ("log10", mp.log10, "250", {}, ""),
    ("log10", mp.log10, "7.5", {}, ""),
    ("sin", mp.sin, "0.7", {}, "rad"),
    ("cos", mp.cos, "2.2", {}, "rad"),
    ("tan", mp.tan, "1.3", {}, "rad"),
    ("sin", O.sin_deg, "37.5", {}, "deg"),
    ("sin", O.sin_deg, "250", {}, "deg"),
    ("cos", lambda x: mp.cos(x * mp.pi / 180), "100", {}, "deg"),
    ("tan", lambda x: mp.tan(x * mp.pi / 180), "71", {}, "deg"),
    ("asin", mp.asin, "0.3", {"unit": "rad"}, ""),
    ("acos", lambda x: mp.acos(x) * 180 / mp.pi, "-0.41", {"unit": "deg"}, ""),
    ("atan", lambda x: mp.atan(x) * 180 / mp.pi, "3.7", {"unit": "deg"}, ""),
    ("normal_cdf", O.normal_cdf, "1.25", {}, ""),
    ("normal_sf", O.normal_sf, "4", {}, ""),
    ("normal_sf", O.normal_sf, "12", {}, ""),
]


@pytest.mark.parametrize("name, f, start, extra, unit", ONE_ARG, ids=[f"{c[0]}({c[2]}{' ' + c[4] if c[4] else ''})" for c in ONE_ARG])
def test_a_one_argument_operator_is_correctly_rounded_on_both_sides_of_a_tie(name, f, start, extra, unit):
    below, above, tie = O.hard_pair(f, O.mp.mpf(start))
    for x in (below, above):
        assert O.distance_to_tie_in_ulps(f, x, tie) < O.mp.mpf(10) ** -10, "a hard case: next to a tie"
        r = ok(inp("x", f"{text(x)} {unit}".strip()), op("y", name, "x", **extra))
        expected = O.exact(f, x)
        assert expected in O.neighbours(tie), "the oracle rounds to a neighbour of the tie"
        assert_correctly_rounded(r, expected, unit=extra.get("unit", ""))
    lower, upper = (number(ok(inp("x", f"{text(x)} {unit}".strip()), op("y", name, "x", **extra)), extra.get("unit", "")) for x in (below, above))
    assert lower != upper, "the two sides of the tie round apart"


def test_deg_to_rad_and_back_are_correctly_rounded_next_to_a_tie():
    to_rad = lambda x: x * O.mp.pi / 180  # noqa: E731
    below, above, _tie = O.hard_pair(to_rad, O.mp.mpf("37.5"))
    for x in (below, above):
        r = ok(inp("a", f"{text(x)} deg"), op("r", "convert", "a", unit="rad"))
        assert_correctly_rounded(r, O.exact(to_rad, x), unit="rad")
    to_deg = lambda x: x * 180 / O.mp.pi  # noqa: E731
    below, above, _tie = O.hard_pair(to_deg, O.mp.mpf("0.6"))
    for x in (below, above):
        r = ok(inp("a", f"{text(x)} rad"), op("r", "convert", "a", unit="deg"))
        assert_correctly_rounded(r, O.exact(to_deg, x), unit="deg")


@pytest.mark.parametrize("y", [Fraction(44, 100), Fraction(1000, 725), Fraction(-2, 3), Fraction(7, 2)], ids=str)
def test_a_non_whole_power_is_correctly_rounded_next_to_a_tie(y):
    f = lambda x: x ** O.mpq(y)  # noqa: E731
    below, above, _tie = O.hard_pair(f, O.mp.mpf("13.7"))
    for x in (below, above):
        r = ok(inp("x", text(x)), inp("y", f"{y.numerator}/{y.denominator}"), op("p", "pow", "x", "y"))
        assert_correctly_rounded(r, O.exact(f, x))


def test_atan2_is_correctly_rounded_next_to_a_tie_in_deg_and_rad():
    for unit in ("deg", "rad"):
        f = lambda y, unit=unit: O.mp.atan2(y, -3) * (180 / O.mp.pi if unit == "deg" else 1)  # noqa: E731
        below, above, _tie = O.hard_pair(f, O.mp.mpf("2.2"))
        for yv in (below, above):
            r = ok(inp("y", f"{text(yv)} mm"), inp("x", "-0.3 cm"), op("a", "atan2", "y", "x", unit=unit))
            assert_correctly_rounded(r, O.exact(f, yv), unit=unit)


def test_the_chi_square_tail_is_correctly_rounded_next_to_a_tie():
    for k in (Fraction(3), Fraction(7, 2)):
        f = lambda x: O.chi2_sf(x, O.mpq(k))  # noqa: E731
        below, above, _tie = O.hard_pair(f, O.mp.mpf("4.4"))
        for x in (below, above):
            r = ok(inp("x", text(x)), inp("k", f"{k.numerator}/{k.denominator}"), op("p", "chi2_sf", "x", "k"))
            assert_correctly_rounded(r, O.exact(f, x))


def test_the_normal_quantile_is_correctly_rounded_next_to_a_tie():
    """p is built from a tie in z: Phi at the tie, cut to 45 digits below and above."""
    with O.mp.workdps(O.DPS):
        tie = O.midpoint_near(O.mp.mpf("1.959963984540054"))
        lo, hi = O.truncations(O.normal_cdf(tie))
    for p, side in ((lo, 0), (hi, 1)):
        r = ok(inp("p", text(p)), op("z", "normal_quantile", "p"))
        assert number(r) == O.neighbours(tie)[side], "the side of the tie its p is on"
        assert O.brackets_quantile(O.normal_cdf, number(r), p)
        assert r["rounded"]["correctly_rounded"] is True


def test_the_student_t_quantile_is_correctly_rounded_next_to_a_tie():
    for nu in (Fraction(4), Fraction(29), Fraction(3, 2)):
        cdf = lambda t: O.t_cdf(t, O.mpq(nu))  # noqa: E731
        with O.mp.workdps(O.DPS):
            tie = O.midpoint_near(O.mp.mpf("2.1"))
            lo, hi = O.truncations(cdf(tie))
        for p, side in ((lo, 0), (hi, 1)):
            r = ok(inp("p", text(p)), inp("nu", f"{nu.numerator}/{nu.denominator}"), op("t", "t_quantile", "p", "nu"))
            assert number(r) == O.neighbours(tie)[side], (nu, side)
            assert O.brackets_quantile(cdf, number(r), p)


@pytest.mark.parametrize("p, nu", [("0.975", "4"), ("0.025", "29"), ("0.999999", "1"), ("0.5000001", "3"), ("1e-12", "1/10"), ("0.9", "1000000000")])
def test_the_student_t_quantile_brackets_its_p_across_its_range(p, nu):
    r = ok(inp("p", p), inp("nu", nu), op("t", "t_quantile", "p", "nu"))
    assert O.brackets_quantile(lambda t: O.t_cdf(t, O.mpq(parse_number(nu))), number(r), parse_number(p)), r


def test_pi_and_e_are_correctly_rounded_at_any_digits_asked():
    for digits in (30, 1, 7, 100, 400):
        for name, value in (("pi", O.mp.pi), ("e", O.mp.e)):
            extra = {} if digits == 30 else {"digits": digits}
            r = ok({"id": name, "op": name, **extra})
            with O.mp.workdps(500):
                assert number(r) == O.rounded(+value, digits), (name, digits)
            assert r["rounded"]["digits"] == digits and r["rounded"]["correctly_rounded"] is True


def test_digits_asked_for_are_given_and_still_correctly_rounded():
    below, _above, _tie = O.hard_pair(O.mp.sqrt, O.mp.mpf("3"), places=60)
    r = ok(inp("x", text(below)), op("s", "sqrt", "x", digits=60))
    assert_correctly_rounded(r, O.exact(O.mp.sqrt, below, places=60), places=60)
    r = ok(inp("x", "2"), op("s", "sqrt", "x", digits=1000))
    with O.mp.workdps(1100):
        assert number(r) == O.rounded(O.mp.sqrt(2), 1000)


@pytest.mark.parametrize("bad", [0, 1001, "30", True, 2.5])
def test_digits_must_be_a_whole_number_from_1_to_1000(bad):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("x", "2"), op("s", "sqrt", "x", digits=bad)))
    assert caught.value.path == "graph.nodes[1].digits"


def test_an_exact_operator_takes_no_digits():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("x", "2"), op("s", "add", "x", "x", digits=10)))
    assert "exact result" in caught.value.problem


# ---------------------------------------------------------------- exact results stay exact


@pytest.mark.parametrize("nodes, expected", [
    ([inp("x", "4"), op("r", "sqrt", "x")], "2"),
    ([inp("x", "9/4"), op("r", "sqrt", "x")], "1.5"),
    ([inp("x", "2.25 mm^2"), op("r", "sqrt", "x")], "1.5 mm"),
    ([inp("x", "0"), op("r", "sqrt", "x")], "0"),
    ([inp("x", "27"), inp("y", "1/3"), op("r", "pow", "x", "y")], "3"),
    ([inp("x", "8 m^3"), inp("y", "1/3"), op("r", "pow", "x", "y")], "2 m"),
    ([inp("x", "0.0016"), inp("y", "0.75"), op("r", "pow", "x", "y")], "0.008"),
    ([inp("x", "0"), inp("y", "0.5"), op("r", "pow", "x", "y")], "0"),
    ([inp("x", "1"), inp("y", "0.37"), op("r", "pow", "x", "y")], "1"),
    ([inp("x", "0"), op("r", "exp", "x")], "1"),
    ([inp("x", "1"), op("r", "ln", "x")], "0"),
    ([inp("x", "1000"), op("r", "log10", "x")], "3"),
    ([inp("x", "0.001"), op("r", "log10", "x")], "-3"),
    ([inp("x", "30 deg"), op("r", "sin", "x")], "0.5"),
    ([inp("x", "-330 deg"), op("r", "sin", "x")], "0.5"),
    ([inp("x", "180 deg"), op("r", "sin", "x")], "0"),
    ([inp("x", "60 deg"), op("r", "cos", "x")], "0.5"),
    ([inp("x", "90 deg"), op("r", "cos", "x")], "0"),
    ([inp("x", "225 deg"), op("r", "tan", "x")], "1"),
    ([inp("x", "0 rad"), op("r", "cos", "x")], "1"),
    ([inp("x", "1/2"), op("r", "asin", "x", unit="deg")], "30 deg"),
    ([inp("x", "-1"), op("r", "acos", "x", unit="deg")], "180 deg"),
    ([inp("x", "0"), op("r", "acos", "x", unit="deg")], "90 deg"),
    ([inp("x", "-1"), op("r", "atan", "x", unit="deg")], "-45 deg"),
    ([inp("y", "2 m"), inp("x", "-2000 mm"), op("r", "atan2", "y", "x", unit="deg")], "135 deg"),
    ([inp("y", "0"), inp("x", "-1"), op("r", "atan2", "y", "x", unit="deg")], "180 deg"),
    ([inp("y", "0"), inp("x", "5"), op("r", "atan2", "y", "x", unit="rad")], "0 rad"),
    ([inp("x", "0 deg"), op("r", "convert", "x", unit="rad")], "0 rad"),
    ([inp("x", "0"), op("r", "normal_cdf", "x")], "0.5"),
    ([inp("x", "12 mm"), inp("m", "1.2 cm"), inp("s", "2 mm"), op("r", "normal_sf", "x", "m", "s")], "0.5"),
    ([inp("p", "0.5"), inp("m", "10 mm"), inp("s", "2 mm"), op("r", "normal_quantile", "p", "m", "s")], "10 mm"),
    ([inp("x", "0"), inp("k", "3"), op("r", "chi2_sf", "x", "k")], "1"),
    ([inp("p", "1/2"), inp("k", "4"), op("r", "t_quantile", "p", "k")], "0"),
])
def test_where_the_result_is_rational_it_stays_exact(nodes, expected):
    r = ok(*nodes)
    assert r["value"] == expected
    assert "rounded" not in r and "exact" not in r


def test_an_exact_result_that_does_not_end_keeps_its_exact_fraction():
    r = ok(inp("x", "8/27"), inp("y", "2/3"), op("r", "pow", "x", "y"))
    assert r == {"node": "r", "value": "0.444444444444444444444444444444", "exact": "4/9"}


def test_whole_powers_and_the_first_increments_operators_are_untouched():
    assert ok(inp("x", "2"), inp("n", "10"), op("r", "pow", "x", "n")) == {"node": "r", "value": "1024"}
    assert ok(inp("a", "0.1"), inp("b", "0.2"), op("r", "add", "a", "b")) == {"node": "r", "value": "0.3"}


def test_a_rational_quantile_found_by_narrowing_comes_back_as_its_decimal():
    """t at p = 1/9 with 2 degrees of freedom is exactly -1.75; at p = 3/4 with 1 it is exactly 1."""
    assert number(ok(inp("p", "1/9"), inp("k", "2"), op("t", "t_quantile", "p", "k"))) == Fraction(-7, 4)
    assert number(ok(inp("p", "3/4"), inp("k", "1"), op("t", "t_quantile", "p", "k"))) == 1


# ---------------------------------------------------------------- units


@pytest.mark.parametrize("nodes, expected", [
    ([inp("x", "9 m^2"), op("r", "sqrt", "x")], "3 m"),
    ([inp("x", "16 m^2/s^2"), op("r", "sqrt", "x")], "4 m/s"),
    ([inp("x", "4 %"), op("r", "sqrt", "x")], "0.2"),
    ([inp("x", "16 mm^4"), inp("y", "1/4"), op("r", "pow", "x", "y")], "2 mm"),
    ([inp("x", "50 %"), op("r", "log10", "x"), op("s", "neg", "r")], None),
    ([inp("x", "3 m"), inp("y", "4000 mm"), op("r", "atan2", "x", "y", unit="rad")], None),
    ([inp("x", "1 deg/s"), op("r", "convert", "x", unit="rad/s")], None),
    ([inp("x", "1 rad/s"), op("r", "convert", "x", unit="deg/min")], None),
    ([inp("x", "1 mm"), inp("m", "1.2 mm"), inp("s", "1 mm"), op("r", "normal_cdf", "x", "m", "s")], None),
    ([inp("p", "0.9"), inp("m", "1 V"), inp("s", "20 mV"), op("r", "normal_quantile", "p", "m", "s")], "V"),
    ([inp("x", "2.47 mm"), op("r", "ceil", "x", places=1)], "2.5 mm"),
])
def test_new_operators_carry_units_by_the_rules(nodes, expected):
    r = ok(*nodes)
    if expected is None:
        return
    if expected == "V":
        assert r["value"].endswith(" V") and r["rounded"]["error_at_most"].endswith(" V")
    else:
        assert r["value"] == expected


def test_converting_deg_to_rad_and_angular_rates_matches_the_oracle():
    r = ok(inp("x", "1 deg/s"), op("r", "convert", "x", unit="rad/min"))
    assert number(r, "rad/min") == O.exact(lambda: 60 * O.mp.pi / 180)
    r = ok(inp("x", "2 rad"), op("r", "convert", "x", unit="deg"))
    assert number(r, "deg") == O.exact(lambda: 360 / O.mp.pi)


@pytest.mark.parametrize("nodes, words", [
    ([inp("x", "2 m"), op("r", "sqrt", "x")], "no exact square root"),
    ([inp("x", "8 m^3"), op("r", "sqrt", "x")], "no exact square root"),
    ([inp("x", "2 m"), inp("y", "0.5"), op("r", "pow", "x", "y")], "is not a unit"),
    ([inp("x", "2 m"), op("r", "exp", "x")], "plain number"),
    ([inp("x", "2 s"), op("r", "ln", "x")], "plain number"),
    ([inp("x", "2 V"), op("r", "log10", "x")], "plain number"),
    ([inp("x", "1"), op("r", "sin", "x")], "takes an angle in deg or rad"),
    ([inp("x", "2 m"), op("r", "cos", "x")], "takes an angle in deg or rad"),
    ([inp("x", "1 deg"), op("r", "asin", "x", unit="deg")], "plain number"),
    ([inp("y", "1 m"), inp("x", "1 s"), op("r", "atan2", "y", "x", unit="deg")], "measure different things"),
    ([inp("x", "1 rad"), op("r", "convert", "x", unit="mm")], "measure different things"),
    ([inp("a", "30 deg"), inp("b", "1 rad"), op("r", "add", "a", "b")], "Convert one first"),
    ([inp("x", "1 mm"), op("r", "normal_cdf", "x")], "plain number"),
    ([inp("x", "1 mm"), inp("m", "1 g"), inp("s", "1 mm"), op("r", "normal_cdf", "x", "m", "s")], "measure different things"),
    ([inp("p", "0.5 mm"), op("r", "normal_quantile", "p")], "a probability"),
    ([inp("x", "2 mm"), inp("k", "3"), op("r", "chi2_sf", "x", "k")], "chi-square statistic"),
    ([inp("p", "0.9"), inp("k", "3 s"), op("r", "t_quantile", "p", "k")], "degrees of freedom"),
])
def test_new_operators_refuse_a_unit_they_cannot_take(nodes, words):
    r = refused(*nodes)
    assert r["kind"] == "unit_mismatch", r
    assert words in r["reason"], r["reason"]


@pytest.mark.parametrize("node, path, words", [
    (op("r", "asin", "x"), "graph.nodes[1].unit", 'needs "unit"'),
    (op("r", "atan", "x", unit="mm"), "graph.nodes[1].unit", '"deg" or "rad"'),
    (op("r", "sqrt", "x", unit="mm"), "graph.nodes[1].unit", "keeps the units"),
    (op("r", "normal_cdf", "x", "x"), "graph.nodes[1].args", "1 ([x], the standard normal) or 3"),
    (op("r", "round", "x", mode="half_up_please"), "graph.nodes[1].mode", "half_even is the default"),
    (op("r", "ceil", "x", mode="half_even"), "graph.nodes[1].mode", "only round takes"),
    (op("r", "sqrt", "x", places=2), "graph.nodes[1].places", "only ceil, floor and round"),
    ({"id": "r", "op": "pi", "args": ["x"]}, "graph.nodes[1].args", "takes no argument"),
])
def test_a_misused_new_field_is_a_malformed_call_naming_it(node, path, words):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("x", "0.5"), node))
    assert caught.value.path == path, caught.value
    assert words in caught.value.problem, caught.value.problem


def test_pi_typed_as_a_value_is_pointed_at_the_constant():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("x", "pi")))
    assert '"op": "pi"' in caught.value.problem


# ---------------------------------------------------------------- domains


@pytest.mark.parametrize("nodes, kind, words", [
    ([inp("x", "-1"), op("r", "sqrt", "x")], "out_of_domain", "no real square root"),
    ([inp("x", "0"), op("r", "ln", "x")], "out_of_domain", "greater than 0"),
    ([inp("x", "-3"), op("r", "log10", "x")], "out_of_domain", "greater than 0"),
    ([inp("x", "1.0001"), op("r", "asin", "x", unit="rad")], "out_of_domain", "from -1 to 1"),
    ([inp("x", "-2"), op("r", "acos", "x", unit="deg")], "out_of_domain", "from -1 to 1"),
    ([inp("x", "90 deg"), op("r", "tan", "x")], "undefined", "no value"),
    ([inp("x", "-270 deg"), op("r", "tan", "x")], "undefined", "no value"),
    ([inp("y", "0 m"), inp("x", "0 mm"), op("r", "atan2", "y", "x", unit="deg")], "undefined", "origin"),
    ([inp("x", "-8"), inp("y", "1/3"), op("r", "pow", "x", "y")], "out_of_domain", "negative number to a non-whole power"),
    ([inp("x", "0"), inp("y", "-0.5"), op("r", "pow", "x", "y")], "division_by_zero", "negative power of zero"),
    ([inp("x", "1"), inp("m", "0"), inp("s", "0"), op("r", "normal_cdf", "x", "m", "s")], "out_of_domain", "standard deviation"),
    ([inp("p", "0.5"), inp("m", "0"), inp("s", "-1"), op("r", "normal_quantile", "p", "m", "s")], "out_of_domain", "standard deviation"),
    ([inp("p", "0"), op("r", "normal_quantile", "p")], "out_of_domain", "strictly between 0 and 1"),
    ([inp("p", "1"), op("r", "normal_quantile", "p")], "out_of_domain", "strictly between 0 and 1"),
    ([inp("p", "120 %"), op("r", "normal_quantile", "p")], "out_of_domain", "strictly between 0 and 1"),
    ([inp("x", "-0.1"), inp("k", "3"), op("r", "chi2_sf", "x", "k")], "out_of_domain", "never negative"),
    ([inp("x", "1"), inp("k", "0"), op("r", "chi2_sf", "x", "k")], "out_of_domain", "degrees of freedom"),
    ([inp("p", "0.9"), inp("k", "-2"), op("r", "t_quantile", "p", "k")], "out_of_domain", "degrees of freedom"),
    ([inp("p", "1.5"), inp("k", "2"), op("r", "t_quantile", "p", "k")], "out_of_domain", "strictly between 0 and 1"),
])
def test_an_argument_outside_its_domain_is_refused_with_its_reason(nodes, kind, words):
    r = refused(*nodes)
    assert r["kind"] == kind, r
    assert words in r["reason"], r["reason"]
    assert r["node"] == "r"


def test_a_rounded_degrees_of_freedom_is_refused():
    r = refused(inp("x", "2"), op("s", "sqrt", "x"), inp("p", "0.9"), op("r", "t_quantile", "p", "s"))
    assert r["kind"] == "out_of_domain" and "must be exact" in r["reason"]


# ---------------------------------------------------------------- the label, carried on


SQRT2 = [inp("two", "2"), op("s", "sqrt", "two")]


def test_arithmetic_on_a_rounded_value_is_labelled_rounded_with_a_true_bound():
    answer = run(*SQRT2, inp("third", "1/3 mm"), inp("unit", "1 mm"), op("sm", "mul", "s", "unit"),
                 op("sum", "add", "sm", "third"), op("big", "mul", "sum", "sum", "sum"), op("q", "div", "big", "third"))
    assert answer["status"] == "ok"
    by = {v["node"]: v for v in answer["values"]}
    with O.mp.workdps(O.DPS):
        s = O.mp.sqrt(2)
        true = {"sm": s, "sum": s + O.mp.mpf(1) / 3, "big": (s + O.mp.mpf(1) / 3) ** 3, "q": 3 * (s + O.mp.mpf(1) / 3) ** 3}
        for node, t in true.items():
            v = by[node]
            assert "exact" not in v
            label = v["rounded"]
            assert label["correctly_rounded"] is False and label["from"] == ["s"] and label["digits"] == 30
            unit = v["value"].split(" ", 1)[1]
            written, bound = number(v, unit), parse_number(label["error_at_most"].split()[0])
            assert abs(O.mpq(written) - t) <= O.mpq(bound), (node, v)
            assert bound < Fraction(1, 10**27) * abs(written), "the bound stays near the precision"


def test_negation_and_absolute_value_keep_a_correctly_rounded_label():
    answer = run(*SQRT2, op("n", "neg", "s"), op("a", "abs", "n"))
    by = {v["node"]: v for v in answer["values"]}
    assert by["n"]["value"] == "-" + by["s"]["value"] and by["n"]["rounded"] == by["s"]["rounded"]
    assert by["a"] == {**by["s"], "node": "a"}


def test_zero_times_a_rounded_value_is_exactly_zero():
    assert ok(*SQRT2, inp("z", "0"), op("r", "mul", "s", "z")) == {"node": "r", "value": "0"}


def test_labels_name_every_rounding_a_value_rests_on():
    answer = run({"id": "pi", "op": "pi"}, inp("d", "37.5 deg"), op("rad", "convert", "d", unit="rad"),
                 op("ratio", "div", "rad", "pi"), inp("r1", "1 rad"), op("plain", "div", "ratio", "r1"),
                 op("half", "sin", "d"), op("both", "add", "plain", "half"))
    by = {v["node"]: v for v in answer["values"]}
    assert by["both"]["rounded"]["from"] == ["rad", "pi", "half"]


def test_a_comparison_its_bound_decides_is_answered():
    assert ok(*SQRT2, inp("c", "1.4142"), op("r", "gt", "s", "c"))["value"] == "true"
    assert ok(*SQRT2, inp("c", "1.4143"), op("r", "lt", "s", "c"))["value"] == "true"
    assert ok(*SQRT2, inp("c", "1.5"), op("r", "eq", "s", "c"))["value"] == "false"
    assert ok(*SQRT2, inp("c", "1.5"), op("r", "ne", "s", "c"))["value"] == "true"


def test_a_comparison_its_bound_cannot_decide_is_refused_never_guessed():
    """sqrt(2) squared is 2 exactly, but its rounded value squared is not: neither
    "equal" nor "greater" can be told from the bound, so both are refused."""
    for name in ("eq", "ge", "le", "lt"):
        r = refused(*SQRT2, op("sq", "mul", "s", "s"), inp("c", "2"), op("r", name, "sq", "c"))
        assert r["kind"] == "undecidable" and r["node"] == "r", r
        assert "does not guess" in r["reason"]


def test_ceil_floor_and_round_of_a_rounded_value_are_exact_when_decided_and_refused_when_not():
    assert ok(*SQRT2, op("r", "ceil", "s", places=5)) == {"node": "r", "value": "1.41422"}
    assert ok(*SQRT2, op("r", "floor", "s", places=28)) == {"node": "r", "value": "1.4142135623730950488016887242"}
    # At 29 places the written value's last digit is itself in question: refused, not guessed.
    assert refused(*SQRT2, op("r", "floor", "s", places=29))["kind"] == "undecidable"
    r = refused(*SQRT2, op("sq", "mul", "s", "s"), op("r", "ceil", "sq"))
    assert r["kind"] == "undecidable" and "could give 2 or 3" in r["reason"]


def test_an_undecidable_division_and_domain_are_refused():
    r = refused(*SQRT2, op("sq", "mul", "s", "s"), inp("c", "2"), op("z", "sub", "sq", "c"), op("r", "div", "c", "z"))
    assert r["kind"] == "undecidable" and "may be zero" in r["reason"]
    r = refused(*SQRT2, op("sq", "mul", "s", "s"), inp("c", "2"), op("z", "sub", "sq", "c"), op("r", "sqrt", "z"))
    assert r["kind"] == "undecidable" and "may be negative" in r["reason"]


def test_a_rounded_argument_gives_a_value_with_a_bound_that_holds():
    answer = run({"id": "pi", "op": "pi"}, inp("six", "6"), op("a", "div", "pi", "six"), inp("r1", "1 rad"),
                 op("ar", "mul", "a", "r1"), op("s", "sin", "ar"), op("z", "normal_quantile", "s"))
    by = {v["node"]: v for v in answer["values"]}
    with O.mp.workdps(O.DPS):
        for node, true in (("s", O.mp.mpf(1) / 2), ("z", O.mp.mpf(0))):
            label = by[node]["rounded"]
            assert label["correctly_rounded"] is False
            assert abs(O.mpq(number(by[node])) - true) <= O.mpq(parse_number(label["error_at_most"]))


# ---------------------------------------------------------------- round, ceil, floor, exactly


@pytest.mark.parametrize("x, name, extra, expected", [
    ("2.5", "round", {}, "2"), ("3.5", "round", {}, "4"), ("-2.5", "round", {}, "-2"),
    ("2.5", "round", {"mode": "half_away_from_zero"}, "3"), ("-2.5", "round", {"mode": "half_away_from_zero"}, "-3"),
    ("2.5", "round", {"mode": "half_toward_zero"}, "2"), ("-2.5", "round", {"mode": "half_toward_zero"}, "-2"),
    ("-2.5", "round", {"mode": "half_up"}, "-2"), ("2.5", "round", {"mode": "half_down"}, "2"),
    ("1/3", "round", {"places": 4}, "0.3333"), ("2/3", "round", {"places": 4}, "0.6667"),
    ("1250", "round", {"places": -2}, "1200"), ("1350", "round", {"places": -2}, "1400"),
    ("2.0736", "ceil", {}, "3"), ("-2.0736", "ceil", {}, "-2"), ("2", "ceil", {}, "2"),
    ("2.0736", "floor", {}, "2"), ("-2.0736", "floor", {}, "-3"), ("15.552 m^3", "ceil", {"places": 1}, "15.6 m^3"),
])
def test_rounding_operators_are_exact(x, name, extra, expected):
    assert ok(inp("x", x), op("r", name, "x", **extra)) == {"node": "r", "value": expected}


# ---------------------------------------------------------------- the record


def test_a_record_says_which_values_were_rounded_and_at_what_precision():
    g = graph(inp("var", "0.053 mm^2", "sample variance"), op("sd", "sqrt", "var", digits=20),
              inp("n", "5", "sample size"), op("rn", "sqrt", "n"), op("se", "div", "sd", "rn"),
              inp("one", "1", "constant"), inp("p", "0.975", "two-sided 95 %"), inp("dof", "4", "n - 1"),
              op("t", "t_quantile", "p", "dof"), op("half", "mul", "t", "se"), result="half")
    ev = evaluate(read_graph(g))
    assert ev.ok, ev.refusal
    rec = R.build(ev, "ci-half-width", None)
    jsonschema.Draft202012Validator(R.schema()).validate(rec)
    by = {v["node"]: v for v in rec["values"]}
    assert by["sd"]["rounded"] == {"digits": 20, "correctly_rounded": True, "error_at_most": "5e-21 mm", "from": ["sd"]}
    assert by["rn"]["rounded"]["digits"] == 30 and by["t"]["rounded"]["correctly_rounded"] is True
    assert by["se"]["rounded"]["from"] == ["sd", "rn"] and by["se"]["rounded"]["digits"] == 30
    assert rec["result"]["rounded"]["from"] == ["t", "sd", "rn"], "in the order its arguments bring them"
    assert rec["result"]["rounded"]["correctly_rounded"] is False
    assert not any("exact" in v for v in rec["values"] if "rounded" in v)
    assert "rounded" in rec["arithmetic"] and "error_at_most" in rec["arithmetic"]
    assert rec["produced_by"]["python_flint"]
    again = R.rerun(R.load(json.loads(R.file_bytes(rec))))
    assert again["reproduces"] is True, again
    rec["values"][1]["rounded"]["error_at_most"] = "1e-30 mm"  # tightening a bound by hand is caught
    rec["content_hash"] = R.content_hash(rec)
    again = R.rerun(R.load(rec))
    assert again["reproduces"] is False and any(d["field"] == "values[sd]" for d in again["differences"])


def test_the_schema_refuses_a_rounded_value_that_also_claims_an_exact_fraction():
    ev = evaluate(read_graph(graph(inp("x", "2", "t"), op("s", "sqrt", "x"))))
    rec = R.build(ev, "s", None)
    rec["result"]["exact"] = "1414213562373095/1000000000000000"
    assert not jsonschema.Draft202012Validator(R.schema()).is_valid(rec)


# ---------------------------------------------------------------- limits


def test_a_huge_exponential_is_sized_from_its_argument_and_stopped():
    r = refused(inp("x", "5000"), op("y", "exp", "x"), limits=L.FLO2_IO)
    assert r["kind"] == "exceeds_limits" and r["limit"]["name"] == "max_digits"
    assert "1e+2171" in r["reason"], r["reason"]


def test_a_power_too_large_to_carry_is_stopped_before_it_is_made():
    r = refused(inp("x", "1e-500"), inp("y", "10.5"), op("p", "pow", "x", "y"), limits=L.FLO2_IO)
    assert r["kind"] == "exceeds_limits" and r["limit"]["name"] == "max_digits"


def test_digits_past_the_hosts_budget_are_stopped_not_guessed():
    r = refused(inp("x", "2"), op("s", "sqrt", "x", digits=1000), limits=L.Limits(max_digits=500))
    assert r["kind"] == "exceeds_limits" and "working precision" in r["reason"]


def test_a_tail_too_far_out_to_carry_is_stopped():
    r = refused(inp("x", "1e6"), op("q", "normal_sf", "x"), limits=L.FLO2_IO)
    assert r["kind"] == "exceeds_limits" and r["limit"]["name"] == "max_digits"


def test_a_sine_of_a_huge_angle_in_radians_is_still_correctly_rounded():
    """10^1990 rad: the angle is reduced by 2 pi to some 2,000 digits first (Arb
    does it inside the enclosure), and it fits flo2.io's profile."""
    nodes = [inp("a", "1e995"), inp("r", "1 rad"), op("x", "mul", "a", "a", "r"), op("s", "sin", "x")]
    r = ok(*nodes, limits=L.FLO2_IO)
    with O.mp.workdps(2100):
        assert number(r) == O.rounded(O.mp.sin(O.mp.mpf(10) ** 1990))
    assert r["rounded"]["correctly_rounded"] is True


def test_the_deadline_stops_rounded_work_too():
    r = refused(*[inp("x", "2"), *[op(f"s{i}", "sqrt", "x", digits=1000) for i in range(50)]], limits=L.Limits(deadline_ms=1))
    assert r["kind"] == "exceeds_limits" and r["limit"]["name"] == "deadline"


def test_a_rounded_calculation_stopped_on_a_small_machine_completes_to_the_direct_record():
    g = graph(inp("x", "2", "t"), op("s", "sqrt", "x", digits=400), inp("y", "1/3", "t"), op("r", "add", "s", "y"))
    small = L.Limits(max_digits=200)
    ev = evaluate(read_graph(g), L.Guard(small))
    assert ev.stopped
    pending = R.build_pending(ev.graph, "root", None, ev.refusal, small)
    completed = R.build(evaluate(read_graph(pending["graph"])), "root", None)
    direct = R.build(evaluate(read_graph(g)), "root", None)
    assert R.file_bytes(completed) == R.file_bytes(direct)
