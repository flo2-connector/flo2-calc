"""The evaluator, directly: exact arithmetic, every operator, reading a graph.

ver:exact-arithmetic and ver:every-operator-family in design 0bee0c00b35845f6.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from conftest import graph, inp, op

from flo2_calc.errors import CallError
from flo2_calc.evaluator import OPS, Quantity, evaluate, evaluation_json, read_graph
from flo2_calc.numbers import format_number, parse_number


def run(*nodes, result=None):
    return evaluation_json(evaluate(read_graph(graph(*nodes, result=result))))


def result(*nodes, result=None):
    answer = run(*nodes, result=result)
    assert answer["status"] == "ok", answer
    return answer["result"]


def value(*nodes, result_=None) -> str:
    return result(*nodes, result=result_)["value"]


def refused(*nodes):
    answer = run(*nodes)
    assert answer["status"] == "refused", answer
    assert answer["result"] is None
    return answer["refused"]


def malformed(g) -> CallError:
    with pytest.raises(CallError) as caught:
        read_graph(g)
    return caught.value


# ---------------------------------------------------------------- exactness


def test_point_one_plus_point_two_is_exactly_point_three():
    r = result(inp("a", "0.1"), inp("b", "0.2"), op("s", "add", "a", "b"))
    assert r == {"node": "s", "value": "0.3"}, "no binary-float 0.30000000000000004, and no 'exact' needed"


def test_point_one_plus_point_two_equals_point_three_by_comparison():
    assert value(inp("a", "0.1"), inp("b", "0.2"), inp("c", "0.3"), op("s", "add", "a", "b"), op("eq", "eq", "s", "c")) == "true"


def test_a_third_times_three_is_exactly_one():
    assert value(inp("one", "1"), inp("three", "3"), op("third", "div", "one", "three"), op("back", "mul", "third", "three")) == "1"


def test_a_value_that_does_not_end_is_rounded_for_display_and_kept_exact():
    r = result(inp("one", "1"), inp("three", "3 mm"), op("third", "div", "one", "three"))
    assert r["value"] == "0.333333333333333333333333333333 1/mm"
    assert r["exact"] == "1/3 1/mm"


def test_the_rounding_is_half_even_to_thirty_significant_digits():
    text, exact = format_number(Fraction(2, 3))
    assert text == "0.666666666666666666666666666667"
    assert exact == "2/3"
    assert len(text.replace("0.", "", 1)) == 30


def test_small_and_large_values_are_written_in_scientific_notation_exactly():
    assert format_number(Fraction(1602176634, 10**28)) == ("1.602176634e-19", None)
    assert format_number(Fraction(10**25)) == ("1e+25", None)
    assert format_number(Fraction(-25, 10)) == ("-2.5", None)
    assert format_number(Fraction(0)) == ("0", None)


@pytest.mark.parametrize("text, expected", [
    ("0.1", Fraction(1, 10)), ("-2.5e3", Fraction(-2500)), (".5", Fraction(1, 2)), ("1/3", Fraction(1, 3)),
    ("-3/4", Fraction(-3, 4)), ("1e-3", Fraction(1, 1000)), ("7", Fraction(7)),
])
def test_numbers_are_read_exactly_from_their_text(text, expected):
    assert parse_number(text) == expected


def test_written_values_read_back_to_the_same_number():
    for q in (Fraction(1, 10), Fraction(254, 10), Fraction(-1, 8), Fraction(1602176634, 10**28), Fraction(10**25)):
        text, exact = format_number(q)
        assert exact is None
        assert parse_number(text) == q


def test_a_json_number_with_a_fraction_part_is_refused_because_it_arrived_as_a_binary_float():
    e = malformed(graph(inp("a", 0.1)))
    assert e.path == "graph.nodes[0].value"
    assert "binary" in e.problem and '"0.1"' in e.problem


def test_json_integers_and_whole_floats_are_exact_and_accepted():
    assert value(inp("a", 2), inp("b", 3.0), op("s", "add", "a", "b")) == "5"


@pytest.mark.parametrize("text", ["3 + * 4", "3 + 4", "3*4", "2^10", "1/2/3", "2 1/2", "3 - 4", "2 mm - 1 mm", "(3+4)", "pi*2"])
def test_an_expression_typed_as_a_value_is_refused_as_one_with_how_to_build_it(text):
    """q092: "3 + * 4" was read as the number 3 and the unit "+ * 4"."""
    e = malformed(graph(inp("a", text)))
    assert e.path == "graph.nodes[0].value"
    assert "looks like an expression" in e.problem
    assert "graph of nodes" in e.problem and '"op": "add"' in e.problem
    assert "is not a unit" not in e.problem


@pytest.mark.parametrize("text", ["5 1/s", "2 m^-2", "3 kg/(m*s^2)", "4 W/(m^2*K)", "10 %", "0.92 EUR/USD"])
def test_a_unit_with_powers_and_a_one_over_is_not_taken_for_an_expression(text):
    assert read_graph(graph(inp("a", text)))


def test_exact_means_exact_for_these_inputs_and_every_answer_says_so():
    """A value built from a typed decimal of pi is exact for that decimal, not
    for pi (round 1: q025, q029, q037, q067)."""
    answer = run(inp("pi_typed", "3.14159265358979323846264338328"), inp("d", "2 mm"), op("c", "mul", "pi_typed", "d"))
    assert answer["status"] == "ok"
    assert answer["exactness"].startswith("Exact for these inputs")
    assert "no more accurate than they are" in answer["exactness"]
    assert "pi" in answer["exactness"]


def test_an_absurd_exponent_is_refused_rather_than_carried():
    e = malformed(graph(inp("a", "1e100000")))
    assert "1e1000" in e.problem


def test_a_value_that_grows_too_large_is_stopped_at_the_digits_budget_not_carried():
    """It used to be a fixed 20,000-bit cap (kind too_large); it is now the
    host's digits budget (limits.py), and passing it is kind exceeds_limits.
    tests/test_limits.py holds every limit's own tests."""
    nodes = [inp("x", "1e999"), inp("n", "1000"), op("big", "pow", "x", "n"), op("bigger", "mul", "big", "big", "big", "big", "big", "big", "big")]
    r = refused(*nodes)
    assert r["kind"] == "exceeds_limits"
    assert r["node"] == "big" and r["limit"]["name"] == "max_digits"


# ---------------------------------------------------------------- arithmetic


@pytest.mark.parametrize("name, args, expected", [
    ("add", ["2", "3", "4.5"], "9.5"),
    ("sub", ["2", "3"], "-1"),
    ("mul", ["2", "3", "0.5"], "3"),
    ("div", ["7", "2"], "3.5"),
    ("neg", ["2.5"], "-2.5"),
    ("abs", ["-2.5"], "2.5"),
    ("pow", ["2", "10"], "1024"),
    ("pow", ["2", "-2"], "0.25"),
    ("min", ["3", "-1", "2"], "-1"),
    ("max", ["3", "-1", "2"], "3"),
])
def test_arithmetic_operators(name, args, expected):
    nodes = [inp(f"a{i}", a) for i, a in enumerate(args)]
    assert value(*nodes, op("r", name, *[n["id"] for n in nodes])) == expected


def test_convert_changes_the_unit_and_keeps_the_quantity():
    assert value(inp("a", "2.5 cm"), op("r", "convert", "a", unit="mm")) == "25 mm"
    assert value(inp("a", "50 %"), op("r", "convert", "a", unit="")) == "0.5"


# ---------------------------------------------------------------- logic


TRUTH = [(False, False), (False, True), (True, False), (True, True)]
EXPECTED = {
    "and": [False, False, False, True],
    "or": [False, True, True, True],
    "nand": [True, True, True, False],
    "nor": [True, False, False, False],
    "xor": [False, True, True, False],
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_logic_operators_by_truth_table(name):
    for (a, b), want in zip(TRUTH, EXPECTED[name], strict=True):
        got = value(inp("a", a), inp("b", b), op("r", name, "a", "b"))
        assert got == ("true" if want else "false"), (name, a, b)


def test_not():
    assert value(inp("a", True), op("r", "not", "a")) == "false"
    assert value(inp("a", "false"), op("r", "not", "a")) == "true"


def test_n_ary_logic():
    assert value(inp("a", True), inp("b", True), inp("c", True), op("r", "xor", "a", "b", "c")) == "true", "odd count"
    assert value(inp("a", True), inp("b", True), inp("c", False), op("r", "and", "a", "b", "c")) == "false"
    assert value(inp("a", False), inp("b", False), inp("c", True), op("r", "or", "a", "b", "c")) == "true"


# ---------------------------------------------------------------- comparison


@pytest.mark.parametrize("name, a, b, expected", [
    ("eq", "1 m", "1000 mm", True), ("ne", "1 m", "1000 mm", False),
    ("lt", "999 mm", "1 m", True), ("le", "1000 mm", "1 m", True),
    ("gt", "1.001 m", "1000 mm", True), ("ge", "999.999 mm", "1 m", False),
    ("eq", "0.1", "1/10", True), ("lt", "1/3", "0.3333333333333333333333333333334", True),
    ("eq", True, True, True), ("ne", True, False, True),
])
def test_comparisons(name, a, b, expected):
    assert value(inp("a", a), inp("b", b), op("r", name, "a", "b")) == ("true" if expected else "false")


# ---------------------------------------------------------------- what a computation refuses


def test_division_by_zero_is_refused_naming_the_node():
    r = refused(inp("a", "1 mm"), inp("z", "0 s"), op("speed", "div", "a", "z"))
    assert r["node"] == "speed" and r["op"] == "div" and r["kind"] == "division_by_zero"
    assert '"z" is zero' in r["reason"]


def test_logic_on_a_number_and_arithmetic_on_true_false_are_refused():
    assert refused(inp("a", "1"), inp("b", True), op("r", "and", "a", "b"))["kind"] == "type_mismatch"
    assert refused(inp("a", "1"), inp("b", True), op("r", "add", "a", "b"))["kind"] == "type_mismatch"
    assert refused(inp("a", "1"), inp("b", True), op("r", "eq", "a", "b"))["kind"] == "type_mismatch"


def test_pow_takes_only_a_plain_whole_exponent():
    assert refused(inp("a", "2"), inp("b", "0.5"), op("r", "pow", "a", "b"))["kind"] == "bad_exponent"
    assert refused(inp("a", "2"), inp("b", "2 mm"), op("r", "pow", "a", "b"))["kind"] == "bad_exponent"
    assert refused(inp("a", "0"), inp("b", "-1"), op("r", "pow", "a", "b"))["kind"] == "division_by_zero"
    assert refused(inp("a", "0"), inp("b", "0"), op("r", "pow", "a", "b"))["kind"] == "undefined"


def test_values_before_a_refusal_are_still_reported():
    answer = run(inp("a", "1"), inp("z", "0"), op("ok", "add", "a", "z"), op("bad", "div", "a", "z"))
    assert answer["status"] == "refused"
    assert [v["node"] for v in answer["values"]] == ["a", "z", "ok"]


# ---------------------------------------------------------------- reading a graph


def test_an_operator_outside_the_first_increment_is_a_malformed_call_naming_the_known_ones():
    e = malformed(graph(inp("a", "1"), inp("b", "2"), op("u", "union", "a", "b")))
    assert e.path == "graph.nodes[2].op"
    assert "'union' is not an operator" in e.problem
    for name in OPS:
        assert name in e.problem
    assert "Set operations come later" in e.problem


def test_the_operator_families_are_the_accepted_ones():
    families = {v[0] for v in OPS.values()}
    assert families == {"arithmetic", "logic", "comparison"}
    assert {k for k, v in OPS.items() if v[0] == "logic"} == {"and", "or", "not", "nor", "nand", "xor"}


@pytest.mark.parametrize("bad, path, words", [
    ({"nodes": []}, "graph.nodes", "at least one node"),
    ({"nodes": [{"id": "a", "value": "1"}, {"id": "a", "value": "2"}]}, "graph.nodes[1].id", "already the id"),
    ({"nodes": [{"id": "a", "op": "add", "args": ["a", "b"]}]}, "graph.nodes[0].args[1]", '"b" is not the id'),
    ({"nodes": [{"id": "a", "value": "1"}, {"id": "n", "op": "neg", "args": ["a", "a"]}]}, "graph.nodes[1].args", "exactly 1"),
    ({"nodes": [{"id": "a", "value": "1", "agrs": []}]}, "graph.nodes[0].agrs", "an input node has only"),
    ({"nodes": [{"id": "1a", "value": "1"}]}, "graph.nodes[0].id", "every node has an id"),
    ({"nodes": [{"id": "a", "value": "1"}], "result": "zz"}, "graph.result", "'zz' is not the id"),
    ({"nodes": [{"id": "a", "value": "twelve"}]}, "graph.nodes[0].value", "is not a value"),
    ({"nodes": [{"id": "a", "value": "1"}, {"id": "c", "op": "convert", "args": ["a"]}]}, "graph.nodes[1].unit", "convert needs"),
    ({"nodes": [{"id": "a", "value": "1", "source": {"design_node": "has space"}}]}, "graph.nodes[0].source.design_node", "no spaces"),
    ({"nodes": [{"id": "a", "value": "1"}], "extra": 1}, "graph.extra", 'only "nodes"'),
])
def test_a_graph_that_cannot_be_read_is_a_malformed_call_naming_the_field(bad, path, words):
    e = malformed(bad)
    assert e.path == path, e
    assert words in e.problem, e


def test_a_cycle_is_a_malformed_call_naming_it():
    e = malformed(graph(op("a", "neg", "b"), op("b", "neg", "c"), op("c", "neg", "a")))
    assert e.path == "graph.nodes"
    assert "cycle" in e.problem and "a -> b -> c -> a" in e.problem


def test_nodes_may_be_listed_in_any_order_and_are_evaluated_after_what_they_take():
    r = run(op("s", "add", "a", "b"), inp("a", "1"), inp("b", "2"), result=None)
    assert r["status"] == "ok"
    assert [v["node"] for v in r["values"]] == ["a", "b", "s"]
    assert r["result"] == {"node": "b", "value": "2"}, "with no result named, the result is the last node listed"


def test_the_result_defaults_to_the_last_node_and_can_be_named():
    assert result(inp("a", "1"), inp("b", "2"))["node"] == "b"
    assert result(inp("a", "1"), inp("b", "2"), result="a")["node"] == "a"


def test_quantities_are_exact_fractions_inside():
    ev = evaluate(read_graph(graph(inp("a", "0.1 mm"))))
    assert ev.values["a"] == Quantity(Fraction(1, 10), (("mm", 1),))
