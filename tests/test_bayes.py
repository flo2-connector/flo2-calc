"""Bayesian updating of an estimate: normal-normal and beta-binomial, with the prior's source kept.

req:bayesian-update-of-an-estimate and cap:bayesian-updating-of-an-estimate-with-its-priors-source-kept
in design 0bee0c00b35845f6 (flo2-calc 0.8.0, dec:v0-8-0-bayes-randomization-shapley-choices,
choices 1 and 2). Every value is checked against an INDEPENDENT answer: the textbook
precision-weighted form (1/s0^2 + n/s^2 and the weighted mean), not the rearranged one
flo2-calc computes; the beta's mean and variance from its own definition; the credible
interval and the standard deviations by mpmath at 120 digits.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import jsonschema
import oracle as O
import pytest
from conftest import graph, inp, op

from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph
from flo2_calc.numbers import parse_number


def run(*nodes, result=None, limits=L.LAPTOP):
    return evaluation_json(evaluate(read_graph(graph(*nodes, result=result)), L.Guard(limits)))


def ok(*nodes, **kw):
    answer = run(*nodes, **kw)
    assert answer["status"] == "ok", answer
    return answer


def by_node(answer):
    return {v["node"]: v for v in answer["values"]}


def number(v: dict, unit: str = "") -> Fraction:
    text = v["value"]
    if unit:
        assert text.endswith(" " + unit), v
        text = text[: -len(unit) - 1]
    return Fraction(Decimal(text))


def exact_of(v: dict) -> Fraction:
    """An exact value: its exact fraction where its text is rounded, else its text."""
    assert "rounded" not in v, v
    return parse_number((v.get("exact") or v["value"]).split(" ")[0])


def textbook_normal(m0, s0, xs, s):
    """The textbook form: posterior precision 1/s0^2 + n/s^2; mean (m0/s0^2 + n xbar/s^2) / precision."""
    n = len(xs)
    xbar = sum(xs, Fraction(0)) / n
    precision = 1 / s0**2 + n / s**2
    return (m0 / s0**2 + n * xbar / s**2) / precision, 1 / precision


HEART = [inp("m0", "72", "2019 cohort study: mean resting heart rate"), inp("s0", "9", "2019 cohort study: between-person sd"),
         inp("x", {"array": ["64", "66", "61", "65"]}, "four morning readings"), inp("s", "4", "the watch's measurement sd")]
NORMAL_OPS = [op("mean", "posterior_normal_mean", "m0", "s0", "x", "s"), op("var", "posterior_normal_variance", "m0", "s0", "x", "s"),
              op("sd", "posterior_normal_sd", "m0", "s0", "x", "s")]


# ---------------------------------------------------------------- normal-normal


def test_the_normal_update_is_exact_and_matches_the_textbook_form():
    answer = ok(*HEART, *NORMAL_OPS, result=["mean", "var", "sd"])
    v = by_node(answer)
    mean, var = textbook_normal(Fraction(72), Fraction(9), [Fraction(x) for x in (64, 66, 61, 65)], Fraction(4))
    assert exact_of(v["mean"]) == mean == Fraction(5472, 85)
    assert exact_of(v["var"]) == var == Fraction(324, 85)
    sd = v["sd"]
    assert sd["rounded"]["correctly_rounded"] is True and "exact" not in sd
    with O.mp.workdps(O.DPS):
        assert number(sd) == O.rounded(O.mp.sqrt(O.mpq(var)))


def test_one_observation_is_one_value_and_units_are_carried():
    """A lab value against a population (round 4's B3): one reading, in ug/L, with the prior's sd in mg/L."""
    answer = ok(inp("m0", "28 ug/L", "national survey: mean"), inp("s0", "0.008 mg/L", "national survey: sd"),
                inp("x", "19 ug/L", "the person's test"), inp("s", "3 ug/L", "the assay's sd"),
                *NORMAL_OPS, result=["mean", "var", "sd"])
    v = by_node(answer)
    mean, var = textbook_normal(Fraction(28), Fraction(8), [Fraction(19)], Fraction(3))
    assert v["mean"]["value"].endswith(" ug/L") and exact_of(v["mean"]) == mean == Fraction(1468, 73)
    assert v["var"]["value"].endswith(" ug^2/L^2") and exact_of(v["var"]) == var
    with O.mp.workdps(O.DPS):
        assert number(v["sd"], "ug/L") == O.rounded(O.mp.sqrt(O.mpq(var)))


def test_a_rational_posterior_sd_stays_exact():
    # s0 = 3, s = 4, one observation: variance 9 * 16 / 25 = 144/25, sd 12/5.
    answer = ok(inp("m0", "10", "p"), inp("s0", "3", "p"), inp("x", "13"), inp("s", "4"), *NORMAL_OPS, result=["var", "sd"])
    v = by_node(answer)
    assert v["var"]["value"] == "5.76" and v["sd"]["value"] == "2.4" and "rounded" not in v["sd"]


def test_the_normal_interval_is_the_posteriors_normal_quantile():
    answer = ok(*HEART, *NORMAL_OPS, inp("lo_p", "0.025"), op("lo", "normal_quantile", "lo_p", "mean", "sd"), result="lo")
    with O.mp.workdps(O.DPS):
        mean, var = Fraction(5472, 85), Fraction(324, 85)
        true = O.mpq(mean) + O.mp.sqrt(O.mpq(var)) * O.mp.sqrt(2) * O.mp.erfinv(O.mp.mpf(-0.95))
        lo = by_node(answer)["lo"]
        assert abs(O.mpq(number(lo)) - true) <= O.mpq(parse_number(lo["rounded"]["error_at_most"]))


def test_the_working_shows_the_formula_the_count_and_the_sum():
    answer = ok(*HEART, *NORMAL_OPS, result=["mean", "var", "sd"])
    lines = {f["node"]: f["text"] for f in answer["formula"]}
    assert lines["mean"] == "mean = (m0 * s^2 + s0^2 * sum(x)) / (s^2 + length(x) * s0^2) = 5472/85"
    assert lines["var"] == "var = s0^2 * s^2 / (s^2 + length(x) * s0^2) = 324/85"
    assert lines["sd"].startswith("sd = sqrt(s0^2 * s^2 / (s^2 + length(x) * s0^2)) ≈ 1.95")
    step = next(w for w in answer["working"] if w["node"] == "mean")
    assert "where n = 4, sum(x) = 256" in step["text"] and "\\sum" in step["latex"]
    detail = by_node(answer)["mean"]["detail"]
    assert detail == [{"name": "n", "value": "4"}, {"name": "sum(x)", "value": "256"}]


def test_a_rounded_input_gives_a_rounded_posterior_with_a_bound_that_holds():
    answer = ok(inp("two", "2"), op("s0", "sqrt", "two"), inp("m0", "5", "prior"), inp("x", "7"), inp("s", "1"),
                op("mean", "posterior_normal_mean", "m0", "s0", "x", "s"), result="mean")
    v = by_node(answer)["mean"]
    assert v["rounded"]["correctly_rounded"] is False and "s0" in v["rounded"]["from"]
    with O.mp.workdps(O.DPS):
        true = (5 * 1 + 2 * 7) / O.mp.mpf(1 + 2)  # (m0 s^2 + s0^2 x) / (s^2 + s0^2), s0^2 = 2
        assert abs(O.mpq(number(v)) - true) <= O.mpq(parse_number(v["rounded"]["error_at_most"]))


@pytest.mark.parametrize("nodes, kind, words", [
    ([inp("m0", "72", "p"), inp("s0", "0", "p"), inp("x", "70"), inp("s", "4")], "out_of_domain", "prior_sd"),
    ([inp("m0", "72", "p"), inp("s0", "9", "p"), inp("x", "70"), inp("s", "-4")], "out_of_domain", "data_sd"),
    ([inp("m0", "72 mm", "p"), inp("s0", "9 mm", "p"), inp("x", "70 g"), inp("s", "4 mm")], "unit_mismatch", "posterior_normal_mean"),
    ([inp("m0", "72", "p"), inp("s0", "9", "p"), inp("x", True), inp("s", "4")], "type_mismatch", "true/false"),
    ([inp("m0", "37 degC", "p"), inp("s0", "1 delta_degC", "p"), inp("x", "38 degC"), inp("s", "1 delta_degC")], "offset_temperature", "K first"),
    ([inp("m0", "72", "p"), inp("s0", "9", "p"), inp("x", {"array": [["1", "2"], ["3", "4"]]}), inp("s", "4")], "shape_mismatch", "1-D"),
])
def test_a_normal_update_that_cannot_be_done_is_refused_with_its_reason(nodes, kind, words):
    answer = run(*nodes, op("mean", "posterior_normal_mean", "m0", "s0", "x", "s"))
    assert answer["status"] == "refused", answer
    r = answer["refused"]
    assert r["kind"] == kind and words in r["reason"], r


# ---------------------------------------------------------------- the prior's source


def test_a_prior_without_a_source_is_refused_naming_the_input():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("m0", "72", None), inp("s0", "9", "cohort"), inp("x", "70"), inp("s", "4"),
                         op("mean", "posterior_normal_mean", "m0", "s0", "x", "s")))
    assert caught.value.path == "graph.nodes[0].source"
    assert '"m0"' in caught.value.problem and "published population" in caught.value.problem


def test_a_prior_computed_from_inputs_needs_each_of_their_sources():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("lo", "60", "reference range, lower end"), inp("hi", "84", None), op("w", "sub", "hi", "lo"),
                         inp("four", "4", "a 95% range is about 4 sd wide"), op("s0", "div", "w", "four"),
                         inp("m0", "72", "cohort"), inp("x", "70"), inp("s", "4"),
                         op("mean", "posterior_normal_mean", "m0", "s0", "x", "s")))
    assert caught.value.path == "graph.nodes[1].source" and '"hi"' in caught.value.problem


def test_the_observations_need_no_source_outside_a_record():
    ok(inp("m0", "72", "cohort"), inp("s0", "9", "cohort"), inp("x", "70", None), inp("s", "4", None),
       op("mean", "posterior_normal_mean", "m0", "s0", "x", "s"))


def test_a_beta_prior_without_a_source_is_refused_too():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", "2", "survey"), inp("b", "8", None), inp("k", "7"), inp("n", "10"),
                         op("m", "posterior_beta_mean", "a", "b", "k", "n")))
    assert caught.value.path == "graph.nodes[1].source"


# ---------------------------------------------------------------- beta-binomial

SURVEY = [inp("a", "2", "2022 user survey, table 3"), inp("b", "8", "2022 user survey, table 3"),
          inp("k", "7", "good days"), inp("n", "10", "days taken")]
BETA_OPS = [op("a2", "posterior_beta_a", "a", "b", "k", "n"), op("b2", "posterior_beta_b", "a", "b", "k", "n"),
            op("bm", "posterior_beta_mean", "a", "b", "k", "n"), op("bv", "posterior_beta_variance", "a", "b", "k", "n"),
            op("bs", "posterior_beta_sd", "a", "b", "k", "n")]


def test_the_beta_update_is_exact_and_matches_the_definitions():
    answer = ok(*SURVEY, *BETA_OPS, result=["a2", "b2", "bm", "bv", "bs"])
    v = by_node(answer)
    a2, b2 = Fraction(9), Fraction(11)
    assert exact_of(v["a2"]) == a2 and exact_of(v["b2"]) == b2
    assert exact_of(v["bm"]) == a2 / (a2 + b2) == Fraction(9, 20)
    # Var = E[p^2] - E[p]^2, from the beta's moments a(a+1)/((a+b)(a+b+1)): another route than flo2-calc's.
    second = a2 * (a2 + 1) / ((a2 + b2) * (a2 + b2 + 1))
    assert exact_of(v["bv"]) == second - (a2 / (a2 + b2)) ** 2 == Fraction(33, 2800)
    with O.mp.workdps(O.DPS):
        assert number(v["bs"]) == O.rounded(O.mp.sqrt(O.mpq(Fraction(33, 2800))))
    lines = {f["node"]: f["text"] for f in answer["formula"]}
    assert lines["bm"] == "bm = (a + k) / (a + b + n) = 0.45"
    step = next(w for w in answer["working"] if w["node"] == "bm")
    assert "(2 + 7) / (2 + 8 + 10)" in step["text"]


def test_the_beta_credible_interval_is_the_posteriors_equal_tailed_quantiles():
    answer = ok(*SURVEY, inp("level", "0.95", "asked"), op("lo", "posterior_beta_interval_lower", "a", "b", "k", "n", "level"),
                op("hi", "posterior_beta_interval_upper", "a", "b", "k", "n", "level"), result=["lo", "hi"])
    v = by_node(answer)
    cdf = lambda x: O.beta_cdf(x, 9, 11)  # noqa: E731
    assert O.brackets_quantile(cdf, number(v["lo"]), Fraction(1, 40))
    assert O.brackets_quantile(cdf, number(v["hi"]), Fraction(39, 40))
    for node in ("lo", "hi"):
        assert v[node]["rounded"]["correctly_rounded"] is True
    lines = {f["node"]: f["text"] for f in answer["formula"]}
    assert lines["lo"].startswith("lo = beta_quantile((1 - level) / 2, a + k, b + n - k) ≈ 0.")
    assert {d["name"]: d["value"] for d in v["hi"]["detail"]} == {"p": "0.975", "posterior a": "9", "posterior b": "11"}


def test_a_uniform_prior_with_no_data_has_an_exact_interval():
    """Beta(1, 1), nothing observed: the posterior is uniform, so its 90% interval is exactly [0.05, 0.95]."""
    answer = ok(inp("a", "1", "uniform prior"), inp("b", "1", "uniform prior"), inp("k", "0"), inp("n", "0"), inp("level", "0.9"),
                op("lo", "posterior_beta_interval_lower", "a", "b", "k", "n", "level"),
                op("hi", "posterior_beta_interval_upper", "a", "b", "k", "n", "level"), result=["lo", "hi"])
    assert [r["value"] for r in answer["results"]] == ["0.05", "0.95"]


@pytest.mark.parametrize("nodes, kind, words", [
    ([inp("a", "0", "s"), inp("b", "8", "s"), inp("k", "7"), inp("n", "10")], "out_of_domain", "a"),
    ([inp("a", "2", "s"), inp("b", "8", "s"), inp("k", "11"), inp("n", "10")], "out_of_domain", "0 to n"),
    ([inp("a", "2", "s"), inp("b", "8", "s"), inp("k", "7/2"), inp("n", "10")], "out_of_domain", "whole"),
    ([inp("a", "2 mm", "s"), inp("b", "8", "s"), inp("k", "7"), inp("n", "10")], "unit_mismatch", "plain"),
])
def test_a_beta_update_that_cannot_be_done_is_refused_with_its_reason(nodes, kind, words):
    answer = run(*nodes, op("m", "posterior_beta_mean", "a", "b", "k", "n"))
    assert answer["status"] == "refused", answer
    assert answer["refused"]["kind"] == kind and words in answer["refused"]["reason"], answer["refused"]


@pytest.mark.parametrize("level, words", [("0", "strictly between 0 and 1"), ("1", "strictly between 0 and 1"), ("95 %", None)])
def test_the_intervals_level_is_a_probability_never_defaulted(level, words):
    nodes = [*SURVEY, inp("level", level), op("lo", "posterior_beta_interval_lower", "a", "b", "k", "n", "level")]
    answer = run(*nodes)
    if words is None:  # 95 % is 0.95
        assert answer["status"] == "ok"
        return
    assert answer["status"] == "refused" and words in answer["refused"]["reason"]
    with pytest.raises(CallError) as caught:
        read_graph(graph(*SURVEY, op("lo", "posterior_beta_interval_lower", "a", "b", "k", "n")))
    assert "exactly 5" in caught.value.problem


# ---------------------------------------------------------------- the record


def test_a_bayesian_update_is_recorded_validates_and_re_runs_byte_for_byte():
    g = graph(*HEART, *NORMAL_OPS, *SURVEY, *BETA_OPS, inp("level", "0.9", "asked"),
              op("lo", "posterior_beta_interval_lower", "a", "b", "k", "n", "level"),
              result=["mean", "var", "sd", "bm", "bs", "lo"])
    g["nodes"][2]["source"] = "four morning readings"
    ev = evaluate(read_graph(g))
    assert ev.ok, ev.refusal
    rec = R.build(ev, "bayes", "req:bayesian-update-of-an-estimate")
    jsonschema.Draft202012Validator(R.schema()).validate(rec)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**rec, "schema_version": 7}, R.schema(7))
    again = R.build(evaluate(read_graph(rec["graph"])), "bayes", "req:bayesian-update-of-an-estimate")
    assert R.file_bytes(again) == R.file_bytes(rec)
    assert R.rerun(R.load(rec))["reproduces"] is True
