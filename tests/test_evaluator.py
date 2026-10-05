"""The evaluator, directly: exact arithmetic, every operator, reading a graph.

ver:exact-arithmetic and ver:every-operator-family in design 0bee0c00b35845f6.
"""

from __future__ import annotations

import re
from decimal import Decimal
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
    assert "expression" in e.problem
    assert "graph of nodes" in e.problem and '"op": "<operator>"' in e.problem
    assert "is not a unit" not in e.problem


@pytest.mark.parametrize("text, where", [
    ("3 + * 4", 'no operand between "+" at character 3 and "*" at character 5'),
    ("3 +", 'nothing after "+" at character 3'),
    ("* 4", 'nothing before "*" at character 1'),
    ("(3 + 4", '"(" at character 1 is never closed'),
    ("3 + 4)", '")" at character 6 closes no "("'),
    ("2 1/2", "two values stand side by side with no operator between them, at character 3"),
    ("3 + () ", 'nothing between "(" at character 5 and ")" at character 6'),
])
def test_a_malformed_expression_is_called_malformed_and_where_with_no_example_to_copy(text, where):
    """Round 2, q092: the refusal of "3 + * 4" showed values "3" and "4" joined
    by add, which is the guess 3 + 4 = 7 the question forbids. Now it says the
    expression is malformed, where, and not to guess; its example is a node's
    SHAPE, with no number and no operator of the input's own."""
    e = malformed(graph(inp("a", text)))
    assert e.path == "graph.nodes[0].value"
    assert "is a malformed expression" in e.problem and where in e.problem, e.problem
    assert "does not guess" in e.problem and "ask what was meant" in e.problem
    example = e.problem[e.problem.index("Build it"):]
    assert not re.search(r"\d", example), "the example holds no number"
    assert '"add"' not in example and "+" not in example and "*" not in example
    assert '"value": "3"' not in e.problem and '"value": "4"' not in e.problem


@pytest.mark.parametrize("text", ["3 + 4", "2^10", "(3+4)", "3 * -4", "3 mm + 4 mm"])
def test_a_well_formed_expression_is_refused_as_an_expression_not_called_malformed(text):
    e = malformed(graph(inp("a", text)))
    assert "is an expression" in e.problem and "malformed" not in e.problem


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


def test_pow_takes_a_plain_exponent_and_refuses_powers_of_zero_that_have_no_value():
    """A non-whole exponent is no longer refused (dec:round-1-fixes-one-to-six):
    2^0.5 is a rounded value now, tested in tests/test_rounded.py."""
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
    assert families == {
        "arithmetic", "logic", "comparison", "functions", "constants", "trigonometry", "rounding", "statistics",
        "units", "decibels", "counting",
        # 0.6.0, arrays (req:flo2-calc-computes-over-arrays)
        "reductions", "statistics over data", "transforms", "complex values", "making and shaping arrays",
    }
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


def test_a_fraction_followed_by_a_decimal_is_an_expression_not_a_division_by_zero():
    """0.4.0 read "1/0.725" as the fraction 1/0 and refused it as a division by zero."""
    e = malformed(graph(inp("a", "1/0.725")))
    assert "is an expression" in e.problem and "divides by zero" not in e.problem


# ---------------------------------------------------------------- counting true values (round 2, fix 4)


def test_count_true_is_an_exact_whole_number():
    """q040: add over booleans was refused and the 5 of 8 was the agent's tally."""
    rows = [inp(f"r{i}", bool(i % 3)) for i in range(8)]
    assert value(*rows, op("n", "count_true", *[f"r{i}" for i in range(8)])) == "5"
    assert value(inp("a", False), op("n", "count_true", "a")) == "0"


def test_booleans_still_never_add_as_numbers():
    r = refused(inp("a", True), inp("b", True), op("s", "add", "a", "b"))
    assert r["kind"] == "type_mismatch"


def test_count_true_takes_only_true_false_values():
    r = refused(inp("a", True), inp("b", "1"), op("n", "count_true", "a", "b"))
    assert r["kind"] == "type_mismatch" and '"b" is the number 1' in r["reason"]


@pytest.mark.parametrize("k, votes, expected", [
    ("2", [True, False, True], "true"),
    ("2", [True, False, False], "false"),
    ("0", [False, False], "true"),
    ("3", [True, True, True], "true"),
])
def test_k_of_n_is_true_when_at_least_k_are_true(k, votes, expected):
    """q047's two-out-of-three, one node instead of three ands and an or."""
    nodes = [inp("k", k)] + [inp(f"b{i}", v) for i, v in enumerate(votes)]
    assert value(*nodes, op("vote", "k_of_n", "k", *[f"b{i}" for i in range(len(votes))])) == expected


@pytest.mark.parametrize("k, kind", [("4", "out_of_domain"), ("-1", "out_of_domain"), ("1.5", "out_of_domain"), ("2 mm", "unit_mismatch")])
def test_k_of_n_refuses_a_k_that_is_not_a_whole_count_of_its_values(k, kind):
    r = refused(inp("k", k), inp("a", True), inp("b", True), inp("c", False), op("vote", "k_of_n", "k", "a", "b", "c"))
    assert r["kind"] == kind and "from 0 to 3" in r["reason"]


def test_k_of_n_needs_k_and_at_least_one_value():
    e = malformed(graph(inp("k", "1"), op("vote", "k_of_n", "k")))
    assert e.path == "graph.nodes[1].args" and "2 to 100" in e.problem


# ---------------------------------------------------------------- several named results (round 2, fix 9)


def test_a_list_of_results_reports_each_by_name_in_its_order():
    """q070's interval came back as only its upper end; q006 and q017 read their numbers out of "values"."""
    answer = run(inp("mid", "12 mm"), inp("half", "0.3 mm"), op("lo", "sub", "mid", "half"), op("hi", "add", "mid", "half"),
                 op("ok", "lt", "lo", "hi"), result=["lo", "hi", "ok"])
    assert answer["status"] == "ok" and "result" not in answer
    assert answer["results"] == [{"node": "lo", "value": "11.7 mm"}, {"node": "hi", "value": "12.3 mm"}, {"node": "ok", "value": "true"}]


def test_one_named_result_is_still_reported_as_result():
    answer = run(inp("a", "1"), inp("b", "2"), op("s", "add", "a", "b"), result="s")
    assert answer["result"] == {"node": "s", "value": "3"} and "results" not in answer


@pytest.mark.parametrize("result, path, words", [
    ([], "graph.result", "at least one node"),
    (["a", "zz"], "graph.result[1]", "'zz' is not the id"),
    (["a", "a"], "graph.result[1]", "named twice"),
    ([3], "graph.result[0]", "is not the id"),
])
def test_a_list_of_results_must_name_each_node_once(result, path, words):
    e = malformed({"nodes": [{"id": "a", "value": "1"}], "result": result})
    assert e.path == path and words in e.problem


def test_a_refused_graph_with_a_list_of_results_gives_none():
    answer = run(inp("a", "2 mm"), inp("b", "3 g"), op("s", "add", "a", "b"), result=["a", "s"])
    assert answer["status"] == "refused" and answer["results"] is None and answer["result"] is None


# ---------------------------------------------------------------- whole numbers as integers (round 2, fix 10)


def test_a_large_whole_number_is_written_in_full_never_with_a_fraction_of_one():
    """q085: 2^1000 showed as 30-digit e-notation beside ".../1"."""
    r = result(inp("x", "2"), inp("n", "1000"), op("p", "pow", "x", "n"))
    assert r == {"node": "p", "value": str(2**1000)}


@pytest.mark.parametrize("text, written", [
    ("2^100", str(2**100)),
    ("1e30", "1" + "0" * 30),
    ("6.02214076e23", "602214076000000000000000"),
    ("1e45", "1e+45"),
])
def test_whole_numbers_are_integers_and_only_a_long_run_of_zeros_keeps_its_short_form(text, written):
    q = Fraction(2) ** 100 if text == "2^100" else Fraction(Decimal(text))
    shown, exact = format_number(q, whole_in_full=True)
    assert (shown, exact) == (written, None)
    assert parse_number(shown) == q


def test_a_whole_value_keeps_its_unit():
    assert value(inp("a", "123456789012345678901234567890123456789012 mm"), inp("b", "1 mm"), op("s", "add", "a", "b")) == \
        "123456789012345678901234567890123456789013 mm"


# ---------------------------------------------------------------- units for an empirical formula (round 2, fix 3)

IPC = [
    inp("I", "2 A", "requirement"), inp("dT", "10 delta_degC", "allowed rise"), inp("k", "0.048", "IPC-2221, external layer"),
    inp("b", "0.44", "IPC-2221"), inp("c", "40/29", "1/0.725, IPC-2221"),
    op("i", "magnitude", "I", unit="A"), op("t", "magnitude", "dT", unit="delta_degC"),
    op("tb", "pow", "t", "b"), op("den", "mul", "k", "tb"), op("q", "div", "i", "den"), op("A", "pow", "q", "c"),
    op("area", "with_unit", "A", unit="mil^2", source="IPC-2221: the cross-section A is in mil^2"),
]


def test_an_empirical_formula_takes_its_numbers_in_named_units_and_states_its_result_unit():
    """q078: the inputs went in as bare numbers and mil^2 came from a typed "1 mil^2" input."""
    answer = run(*IPC)
    values = {v["node"]: v for v in answer["values"]}
    assert values["i"]["value"] == "2" and values["t"]["value"] == "10"
    assert values["area"]["value"].endswith(" mil^2") and values["area"]["value"].startswith("42.3930671489")
    assert "rounded" in values["area"]


def test_magnitude_reads_a_number_only_in_a_unit_of_what_the_quantity_measures():
    assert value(inp("I", "2 A"), op("i", "magnitude", "I", unit="mA")) == "2000"
    assert value(inp("T", "25 degC"), op("t", "magnitude", "T", unit="K")) == "298.15"
    r = refused(inp("I", "2 A"), op("i", "magnitude", "I", unit="mil"))
    assert r["kind"] == "unit_mismatch" and "never taken in the wrong unit" in r["reason"]
    r = refused(inp("I", "2"), op("i", "magnitude", "I", unit="A"))
    assert r["kind"] == "unit_mismatch", "a bare 2000 is never read as amperes"


def test_with_unit_needs_a_plain_number_a_unit_and_where_that_unit_comes_from():
    e = malformed(graph(inp("y", "42.39"), op("a", "with_unit", "y", unit="mil^2")))
    assert e.path == "graph.nodes[1].source" and "IPC-2221" in e.problem
    e = malformed(graph(inp("y", "42.39"), op("a", "with_unit", "y", source="x")))
    assert e.path == "graph.nodes[1].unit"
    e = malformed(graph(inp("y", "42.39"), op("a", "with_unit", "y", unit="", source="x")))
    assert e.path == "graph.nodes[1].unit"
    r = refused(inp("y", "1 mm^2"), op("a", "with_unit", "y", unit="mil^2", source="x"))
    assert r["kind"] == "unit_mismatch" and "never replaced" in r["reason"], "a typed 1 mm^2 can no longer slip in"


def test_only_an_input_and_with_unit_take_a_source():
    e = malformed(graph(inp("y", "2"), op("a", "neg", "y", source="x")))
    assert e.path == "graph.nodes[1].source"


def test_the_stated_unit_and_its_source_are_kept_in_the_graph():
    g = read_graph(graph(*IPC))
    kept = g.to_json()["nodes"][-1]
    assert kept == {"id": "area", "op": "with_unit", "args": ["A"], "unit": "mil^2", "source": "IPC-2221: the cross-section A is in mil^2"}
