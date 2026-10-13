"""Shapley values: credit for an outcome shared among a few factors, from a table naming every combination.

req:shapley-credit-over-few-factors and cap:shapley-values-share-credit-among-a-few-factors in
design 0bee0c00b35845f6 (flo2-calc 0.8.0, dec:v0-8-0-bayes-randomization-shapley-choices,
choices 4 and 5). Each value is checked against an INDEPENDENT computation written here: the
marginal contribution of each factor averaged over every ORDER in which the factors can be
added (flo2-calc sums over subsets with weights). The table must name every combination once;
past max_shapley_factors the call is refused, naming the limit.
"""

from __future__ import annotations

import itertools
import random
from fractions import Fraction

import jsonschema
import pytest
from conftest import graph, inp, op

from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph
from flo2_calc.numbers import parse_number


def run(*nodes, limits=L.LAPTOP, result=None):
    return evaluation_json(evaluate(read_graph(graph(*nodes, result=result)), L.Guard(limits)))


def by_orders(factors: list[str], table: dict[frozenset, Fraction]) -> dict[str, Fraction]:
    """Shapley's definition: each factor's marginal contribution averaged over every order of adding them."""
    phi = {f: Fraction(0) for f in factors}
    orders = list(itertools.permutations(factors))
    for order in orders:
        present: set[str] = set()
        for f in order:
            phi[f] += table[frozenset(present | {f})] - table[frozenset(present)]
            present.add(f)
    return {f: v / len(orders) for f, v in phi.items()}


def table_nodes(factors: list[str], table: dict[frozenset, Fraction], unit: str = "d", order: list[frozenset] | None = None):
    combos = order or list(table)
    values = [str(table[c]) for c in combos]
    combinations = [[f for f in factors if f in c] for c in combos]
    v = {"array": values}
    if unit:
        v["unit"] = unit
    return [inp("v", v, "symptom-free days, one month per combination"),
            op("phi", "shapley_values", "v", factors=factors, combinations=combinations)]


THREE = ["sleep", "diet", "walk"]
S1 = {frozenset(): Fraction(10), frozenset({"sleep"}): Fraction(14), frozenset({"diet"}): Fraction(12),
      frozenset({"walk"}): Fraction(11), frozenset({"sleep", "diet"}): Fraction(18), frozenset({"sleep", "walk"}): Fraction(16),
      frozenset({"diet", "walk"}): Fraction(13), frozenset(THREE): Fraction(21)}


def values_of(answer: dict) -> list[Fraction]:
    r = answer["result"]
    assert r["array"]["kind"] == "exact", r
    return [parse_number(t) for t in r["array"]["values"]]


def test_three_factors_match_the_average_over_every_order():
    answer = run(*table_nodes(THREE, S1))
    assert answer["status"] == "ok", answer
    expected = by_orders(THREE, S1)
    assert values_of(answer) == [expected[f] for f in THREE]
    assert answer["result"]["array"]["unit"] == "d"
    assert sum(values_of(answer)) == 11


@pytest.mark.parametrize("k, seed", [(1, 1), (2, 2), (4, 3), (5, 4), (6, 5)])
def test_random_tables_match_the_average_over_every_order(k, seed):
    rnd = random.Random(seed)
    factors = [f"f{i}" for i in range(k)]
    table = {frozenset(c): Fraction(rnd.randint(-50, 50), rnd.randint(1, 7))
             for r in range(k + 1) for c in itertools.combinations(factors, r)}
    order = list(table)
    rnd.shuffle(order)  # the table may list its combinations in any order
    answer = run(*table_nodes(factors, table, unit="", order=order))
    assert answer["status"] == "ok", answer
    expected = by_orders(factors, table)
    assert values_of(answer) == [expected[f] for f in factors]


def test_the_working_shows_each_value_and_that_they_sum_to_all_minus_none():
    answer = run(*table_nodes(THREE, S1))
    detail = {d["name"]: d["value"] for d in answer["result"]["detail"]}
    expected = by_orders(THREE, S1)
    assert parse_number(detail["phi(sleep)"].split()[0]) == expected["sleep"]
    assert detail["v(all)"] == "21 d" and detail["v(none)"] == "10 d"
    assert detail["v(all) - v(none)"] == "11 d" and detail["sum of the values"] == "11 d"
    step = next(w for w in answer["working"] if w["node"] == "phi")
    assert "v(all) - v(none) = 11 d" in step["text"] and "sum of the values = 11 d" in step["text"]
    line = {f["node"]: f["text"] for f in answer["formula"]}["phi"]
    assert line.startswith("phi = shapley_values(v; factors=sleep, diet, walk)")


# ---------------------------------------------------------------- the table must name every combination


def call_error(factors, combinations, values=None) -> CallError:
    values = values or [str(i) for i in range(len(combinations))]
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("v", {"array": values}), op("phi", "shapley_values", "v", factors=factors, combinations=combinations)))
    return caught.value


def test_a_missing_combination_is_refused_naming_it():
    combos = [[f for f in THREE if f in c] for c in S1 if c != frozenset({"diet", "walk"})]
    e = call_error(THREE, combos)
    assert e.path == "graph.nodes[1].combinations"
    assert "diet and walk present, sleep absent" in e.problem and "1 of the 8" in e.problem


def test_a_combination_named_twice_is_refused_naming_both_places():
    combos = [[], ["sleep"], ["diet"], ["walk"], ["sleep", "diet"], ["diet", "sleep"], ["diet", "walk"], ["sleep", "diet", "walk"]]
    e = call_error(THREE, combos)
    assert e.path == "graph.nodes[1].combinations[5]" and "combinations[4]" in e.problem


@pytest.mark.parametrize("factors, combinations, path, words", [
    (THREE, [[], ["sleep"], ["diet"], ["walk"], ["sleep", "diet"], ["sleep", "walk"], ["diet", "walk"], ["sleep", "diet", "run"]],
     "graph.nodes[1].combinations[7][2]", "'run' is not one of the factors"),
    (THREE, [[], ["sleep"], ["diet"], ["walk"], ["sleep", "sleep"], ["sleep", "walk"], ["diet", "walk"], ["sleep", "diet", "walk"]],
     "graph.nodes[1].combinations[4][1]", "twice"),
    (["a", "a"], [[], ["a"], ["a"], ["a", "a"]], "graph.nodes[1].factors[1]", "twice"),
    ([], [[]], "graph.nodes[1].factors", "at least one"),
    (["a b"], [[], ["a b"]], "graph.nodes[1].factors[0]", "a letter or _"),
    (THREE, "all", "graph.nodes[1].combinations", "a list"),
])
def test_a_malformed_table_is_a_malformed_call_naming_the_field(factors, combinations, path, words):
    e = call_error(factors, combinations, ["1"] * (len(combinations) if isinstance(combinations, list) else 2))
    assert e.path == path and words in e.problem, (e.path, e.problem)


@pytest.mark.parametrize("missing", ["factors", "combinations"])
def test_factors_and_combinations_are_required(missing):
    node = op("phi", "shapley_values", "v", factors=["a"], combinations=[[], ["a"]])
    del node[missing]
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("v", {"array": ["1", "2"]}), node))
    assert caught.value.path == f"graph.nodes[1].{missing}"


def test_an_outcome_count_that_does_not_match_the_combinations_is_refused():
    answer = run(inp("v", {"array": ["1", "2", "3"]}), op("phi", "shapley_values", "v", factors=["a"], combinations=[[], ["a"]]))
    assert answer["refused"]["kind"] == "shape_mismatch" and "2 combinations" in answer["refused"]["reason"]


@pytest.mark.parametrize("value, kind", [({"array": [True, False]}, "type_mismatch"), ("3", "type_mismatch"),
                                         ({"array": [["1", "2"], ["3", "4"]]}, "shape_mismatch")])
def test_the_outcomes_must_be_a_1_d_array_of_numbers(value, kind):
    answer = run(inp("v", value), op("phi", "shapley_values", "v", factors=["a"], combinations=[[], ["a"]]))
    assert answer["refused"]["kind"] == kind, answer


# ---------------------------------------------------------------- the host's limit on factors


def full_table(k: int) -> list[dict]:
    factors = [f"f{i}" for i in range(k)]
    combos = [[f for j, f in enumerate(factors) if m >> j & 1] for m in range(1 << k)]
    return [inp("v", {"array": [str(m % 7) for m in range(1 << k)]}),
            op("phi", "shapley_values", "v", factors=factors, combinations=combos)]


def test_past_the_hosts_factor_limit_the_call_is_refused_naming_the_limit():
    answer = run(*full_table(5), limits=L.Limits(max_shapley_factors=4))
    r = answer["refused"]
    assert r["kind"] == "exceeds_limits" and r["limit"]["name"] == "max_shapley_factors"
    assert r["limit"]["value"] == 4 and r["limit"]["needed_at_least"] == 5
    assert r["limit"]["setting"] == "--max-shapley-factors or FLO2_CALC_MAX_SHAPLEY_FACTORS"
    assert "5 factors" in r["reason"] and "2^5 = 32" in r["reason"]
    assert run(*full_table(4), limits=L.Limits(max_shapley_factors=4))["status"] == "ok"


def test_flo2_ios_twelve_factors_are_computed_exactly():
    answer = run(*full_table(12), limits=L.FLO2_IO)
    assert answer["status"] == "ok" and len(answer["result"]["array"]["values"]) == 12


def test_a_shapley_record_validates_re_runs_and_a_stopped_one_completes():
    g = read_graph(graph(*table_nodes(THREE, S1)))
    rec = R.build(evaluate(g), "credit", None)
    jsonschema.Draft202012Validator(R.schema()).validate(rec)
    assert rec["graph"]["nodes"][1]["factors"] == THREE
    assert R.rerun(R.load(rec))["reproduces"] is True
    small = L.Limits(max_shapley_factors=2)
    ev = evaluate(g, L.Guard(small))
    pending = R.build_pending(g, "credit", None, ev.refusal, small)
    jsonschema.Draft202012Validator(R.schema()).validate(pending)
    assert "max_shapley_factors of at least 3 factors" in R.needs_of(pending["stopped"])
